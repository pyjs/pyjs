{
  description = "PyJS Python-to-JavaScript transpiler";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };
  };

  outputs =
    {
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs lib.systems.flakeExposed;
      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
      overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };
      editableOverlay = workspace.mkEditablePyprojectOverlay { root = "$REPO_ROOT"; };
      pythonSets = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        (pkgs.callPackage pyproject-nix.build.packages { python = pkgs.python314; }).overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.wheel
            overlay
          ]
        )
      );
    in
    {
      packages = forAllSystems (
        system:
        let
          pythonSet = pythonSets.${system};
          inherit (nixpkgs.legacyPackages.${system}.callPackages pyproject-nix.build.util { }) mkApplication;
        in
        {
          default = mkApplication {
            venv = pythonSet.mkVirtualEnv "pyjs" workspace.deps.default;
            package = pythonSet.pyjs;
          };
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonSet = pythonSets.${system}.overrideScope editableOverlay;
          virtualenv = pythonSet.mkVirtualEnv "pyjs-dev" workspace.deps.all;
          commonShell = {
            packages = [
              virtualenv
              pkgs.uv
            ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
              if [[ $- == *i* ]]; then
                user_shell=$(python -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_shell)')
                if [[ -x "$user_shell" ]]; then
                  export SHELL="$user_shell"
                  exec "$user_shell"
                fi
              fi
            '';
          };
        in
        {
          default = pkgs.mkShell commonShell;
          perf = pkgs.mkShell (
            commonShell
            // {
              packages = commonShell.packages ++ [
                pkgs.nodejs_26
                pkgs.llvmPackages_21.clang
                pkgs.rustc
                pkgs.zulu27
              ];
            }
          );
        }
      );
    };
}
