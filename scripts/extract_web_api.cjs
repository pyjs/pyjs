const fs = require("fs");
const path = require("path");

const [moduleRoot, outputPath] = process.argv.slice(2);
if (!moduleRoot || !outputPath) {
  throw new Error("usage: node extract_web_api.cjs NODE_MODULE_ROOT OUTPUT.json");
}

const fromModules = (name) => require(path.join(moduleRoot, name));
const webref = fromModules("@webref/idl");
const bcd = fromModules("@mdn/browser-compat-data");
const ts = fromModules("typescript");

function idlType(type) {
  if (!type) return "undefined";
  let value;
  if (type.union) {
    value = `(${type.idlType.map(idlType).join(" or ")})`;
  } else if (type.generic) {
    const arguments = Array.isArray(type.idlType) ? type.idlType.map(idlType) : [idlType(type.idlType)];
    value = `${type.generic}<${arguments.join(", ")}>`;
  } else if (typeof type.idlType === "string") {
    value = type.idlType;
  } else {
    value = String(type.idlType);
  }
  return type.nullable ? `${value}?` : value;
}

function defaultValue(value) {
  if (value === null || value === undefined) return null;
  if (value.type === "dictionary") return "{}";
  if (value.type === "sequence") return "[]";
  if (value.type === "null") return "null";
  if (value.type === "string") return JSON.stringify(value.value);
  if (value.value !== undefined) return String(value.value);
  return String(value.type);
}

function argument(value) {
  return {
    name: value.name,
    type: idlType(value.idlType),
    default: defaultValue(value.default),
    optional: Boolean(value.optional),
    variadic: Boolean(value.variadic),
  };
}

function member(value, source) {
  if (value.type === "field") {
    return {
      kind: "field",
      name: value.name,
      type: idlType(value.idlType),
      default: defaultValue(value.default),
      required: Boolean(value.required),
      source,
    };
  }
  if (value.type === "const") {
    return {
      kind: "constant",
      name: value.name,
      type: idlType(value.idlType),
      value: defaultValue(value.value),
      source,
    };
  }
  if (value.type === "attribute") {
    return {
      kind: "attribute",
      name: value.name,
      type: idlType(value.idlType),
      readonly: Boolean(value.readonly),
      static: value.special === "static",
      source,
    };
  }
  if (value.type === "constructor") {
    return {
      kind: "constructor",
      name: "__init__",
      type: "undefined",
      arguments: value.arguments.map(argument),
      source,
    };
  }
  if (value.type === "operation") {
    const specialNames = {
      getter: "__getitem__",
      setter: "__setitem__",
      deleter: "__delitem__",
    };
    const name = value.name || specialNames[value.special];
    if (!name) return null;
    const type = idlType(value.idlType);
    return {
      kind: "method",
      name,
      type,
      arguments: value.arguments.map(argument),
      static: value.special === "static",
      special: value.name ? "" : value.special || "",
      asynchronous: type.startsWith("Promise<"),
      source,
    };
  }
  return null;
}

function supportVersion(value) {
  const statements = Array.isArray(value) ? value : [value];
  for (const statement of statements) {
    if (!statement || statement.flags || statement.prefix || statement.alternative_name) continue;
    if (statement.version_added !== null && statement.version_added !== false) {
      return statement.version_added;
    }
  }
  return null;
}

function compatibility(value) {
  if (!value || !value.__compat) return null;
  const compat = value.__compat;
  const specUrls = compat.spec_url || [];
  return {
    mdn_url: compat.mdn_url || null,
    spec_urls: Array.isArray(specUrls) ? specUrls : [specUrls],
    status: {
      deprecated: Boolean(compat.status && compat.status.deprecated),
      experimental: Boolean(compat.status && compat.status.experimental),
      standard_track: compat.status ? Boolean(compat.status.standard_track) : true,
    },
    support: {
      chrome: supportVersion(compat.support && compat.support.chrome),
      safari: supportVersion(compat.support && compat.support.safari),
    },
  };
}

function isSupported(value) {
  if (!value) return true;
  return value.support.chrome !== null || value.support.safari !== null;
}

function tsName(node, source) {
  if (!node) return null;
  if (ts.isIdentifier(node) || ts.isStringLiteral(node) || ts.isNumericLiteral(node)) return node.text;
  return node.getText(source);
}

function typescriptSurface() {
  const filename = path.join(moduleRoot, "@types", "web", "ts5.9", "index.d.ts");
  const source = ts.createSourceFile(
    filename,
    fs.readFileSync(filename, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  );
  const definitions = new Map();
  const get = (name) => {
    if (!definitions.has(name)) {
      definitions.set(name, { kinds: new Set(), bases: new Set(), members: new Map(), alias: null });
    }
    return definitions.get(name);
  };
  const typeText = (value) => (value ? value.getText(source) : null);
  const normalizedMember = (value, name) => {
    let kind = "member";
    if (ts.isConstructSignatureDeclaration(value)) kind = "constructor";
    else if (ts.isMethodSignature(value) || ts.isMethodDeclaration(value)) kind = "method";
    else if (ts.isPropertySignature(value) || ts.isPropertyDeclaration(value)) kind = "property";
    else if (ts.isGetAccessorDeclaration(value)) kind = "getter";
    else if (ts.isSetAccessorDeclaration(value)) kind = "setter";
    else if (ts.isCallSignatureDeclaration(value)) kind = "call";
    return {
      kind,
      name,
      type: typeText(value.type),
      parameters: [...(value.parameters || [])].map((parameter) => ({
        name: tsName(parameter.name, source),
        type: typeText(parameter.type),
        optional: Boolean(parameter.questionToken || parameter.initializer),
        variadic: Boolean(parameter.dotDotDotToken),
      })),
      optional: Boolean(value.questionToken),
      readonly: Boolean(value.modifiers && value.modifiers.some((item) => item.kind === ts.SyntaxKind.ReadonlyKeyword)),
      signature: value.getText(source),
    };
  };
  const addMembers = (target, members) => {
    for (const value of members || []) {
      const name = ts.isConstructSignatureDeclaration(value) ? "__init__" : tsName(value.name, source);
      if (!name) continue;
      if (!target.members.has(name)) target.members.set(name, []);
      target.members.get(name).push(normalizedMember(value, name));
    }
  };

  for (const statement of source.statements) {
    if (ts.isInterfaceDeclaration(statement)) {
      const target = get(statement.name.text);
      target.kinds.add("interface");
      addMembers(target, statement.members);
      for (const clause of statement.heritageClauses || []) {
        for (const type of clause.types) target.bases.add(type.expression.getText(source));
      }
    } else if (ts.isTypeAliasDeclaration(statement)) {
      const target = get(statement.name.text);
      target.kinds.add("alias");
      if (ts.isTypeLiteralNode(statement.type)) addMembers(target, statement.type.members);
      else target.alias = typeText(statement.type);
    } else if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        const name = tsName(declaration.name, source);
        if (!name || !declaration.type || !ts.isTypeLiteralNode(declaration.type)) continue;
        const target = get(name);
        target.kinds.add("value");
        addMembers(target, declaration.type.members);
      }
    }
  }

  const inherited = (name, active = new Set()) => {
    if (active.has(name) || !definitions.has(name)) return new Map();
    active.add(name);
    const definition = definitions.get(name);
    const result = new Map([...definition.members].map(([member, values]) => [member, [...values]]));
    for (const base of definition.bases) {
      for (const [member, values] of inherited(base, active)) {
        if (!result.has(member)) result.set(member, []);
        result.get(member).push(...values);
      }
    }
    active.delete(name);
    return result;
  };
  const result = {};
  for (const [name, value] of definitions) {
    result[name] = {
      kinds: [...value.kinds].sort(),
      bases: [...value.bases].sort(),
      alias: value.alias,
      members: Object.fromEntries([...inherited(name)].sort(([left], [right]) => left.localeCompare(right))),
    };
  }
  return { version: ts.version, filename, definitions: result };
}

async function buildRegistry() {
  const parsed = await webref.parseAll();
  const definitions = new Map();
  const aliases = {};
  const mixins = new Map();
  const includes = [];
  const unhandled = new Set();
  const sources = {};
  const webrefRoot = path.dirname(require.resolve(path.join(moduleRoot, "@webref/idl/package.json")));

  for (const [shortname, constructs] of Object.entries(parsed).sort()) {
    const source = `${shortname}.idl`;
    const text = fs.readFileSync(path.join(webrefRoot, source), "utf8");
    const sourceMatch = text.match(/^\/\/ Source: (.+?) \((https?:\/\/[^)]+)\)/m);
    sources[source] = sourceMatch ? { title: sourceMatch[1], url: sourceMatch[2] } : {};
    for (const construct of constructs) {
      if (construct.type === "enum") {
        aliases[construct.name] = "DOMString";
        continue;
      }
      if (construct.type === "typedef") {
        aliases[construct.name] = idlType(construct.idlType);
        continue;
      }
      if (construct.type === "callback") {
        aliases[construct.name] = "callable";
        continue;
      }
      if (construct.type === "includes") {
        includes.push({ target: construct.target, mixin: construct.includes, source });
        continue;
      }
      if (construct.type === "interface mixin") {
        if (!mixins.has(construct.name)) mixins.set(construct.name, []);
        mixins.get(construct.name).push(...construct.members.map((value) => member(value, source)).filter(Boolean));
        continue;
      }
      if (!["interface", "dictionary", "callback interface"].includes(construct.type)) {
        unhandled.add(construct.type);
        continue;
      }
      const kind = construct.type === "dictionary" ? "dictionary" : "interface";
      if (!definitions.has(construct.name)) {
        definitions.set(construct.name, {
          kind,
          name: construct.name,
          base: null,
          source: null,
          sources: new Set(),
          members: [],
        });
      }
      const definition = definitions.get(construct.name);
      definition.sources.add(source);
      if (!construct.partial) {
        definition.source ||= source;
        definition.base ||= construct.inheritance || null;
      }
      for (const value of construct.members) {
        const parsedMember = member(value, source);
        if (parsedMember) definition.members.push(parsedMember);
        else unhandled.add(`${construct.type}.${value.type}`);
      }
    }
  }

  for (const include of includes) {
    if (!definitions.has(include.target)) {
      definitions.set(include.target, {
        kind: "interface",
        name: include.target,
        base: null,
        source: null,
        sources: new Set(),
        members: [],
      });
    }
    const definition = definitions.get(include.target);
    definition.sources.add(include.source);
    for (const value of mixins.get(include.mixin) || []) definition.members.push(value);
  }

  const typescript = typescriptSurface();
  const output = [];
  for (const definition of definitions.values()) {
    const bcdDefinition = bcd.api[definition.name];
    const compat = compatibility(bcdDefinition);
    const tsDefinition = typescript.definitions[definition.name] || null;
    const seen = new Set();
    const members = [];
    for (const value of definition.members) {
      const signature = `${value.kind}:${value.name}:${value.type}:${JSON.stringify(value.arguments || [])}:${value.source}`;
      if (seen.has(signature)) continue;
      seen.add(signature);
      const feature = value.kind === "constructor" ? definition.name : value.name;
      const memberCompatibility = compatibility(bcdDefinition && bcdDefinition[feature]);
      members.push({
        ...value,
        compatibility: memberCompatibility,
        included_by_browser_policy: isSupported(memberCompatibility),
        typescript: tsDefinition ? tsDefinition.members[value.name] || [] : [],
      });
    }
    output.push({
      ...definition,
      sources: [...definition.sources].sort(),
      members,
      compatibility: compat,
      included_by_browser_policy: isSupported(compat),
      typescript: tsDefinition
        ? {
            kinds: tsDefinition.kinds,
            bases: tsDefinition.bases,
            extra_members: Object.keys(tsDefinition.members)
              .filter((name) => !members.some((value) => value.name === name))
              .sort(),
          }
        : null,
    });
  }
  output.sort((left, right) => left.name.localeCompare(right.name));
  const webidlNames = new Set(output.map((value) => value.name));
  const typescriptNames = new Set(Object.keys(typescript.definitions));
  return {
    generator: {
      webref_idl_version: fromModules("@webref/idl/package.json").version,
      mdn_bcd_version: fromModules("@mdn/browser-compat-data/package.json").version,
      typescript_version: typescript.version,
      types_web_version: fromModules("@types/web/package.json").version,
    },
    browser_policy: {
      primary: "chrome",
      secondary: "safari",
      excludes_vendor_only: ["firefox", "opera"],
    },
    aliases,
    typescript_aliases: Object.fromEntries(
      Object.entries(typescript.definitions)
        .filter(([, value]) => value.alias)
        .map(([name, value]) => [name, value.alias]),
    ),
    sources,
    definitions: output,
    unhandled: [...unhandled].sort(),
    validation: {
      typescript_only_definitions: [...typescriptNames].filter((name) => !webidlNames.has(name)).sort(),
      webidl_only_definitions: [...webidlNames].filter((name) => !typescriptNames.has(name)).sort(),
    },
  };
}

buildRegistry().then((registry) => {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(registry, null, 2)}\n`);
});
