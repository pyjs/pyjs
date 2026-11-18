import shutil
import subprocess

import pytest

from pyjs.testing.espresso import espresso_android_class


def test_resume_bridge_orders_input_barrier_and_reports_connection_failure(tmp_path):
    javac = shutil.which("javac")
    java = shutil.which("java")
    if javac is None or java is None:
        pytest.skip("a JDK is required for the Android bridge contract")
    sources = {
        "android/os/Build.java": '''
package android.os;
public class Build {
    public static class VERSION { public static int SDK_INT = 35; }
}
''',
        "android/content/Intent.java": '''
package android.content;
public class Intent {}
''',
        "android/app/UiAutomation.java": '''
package android.app;
public class UiAutomation {
    public static String events = "";
    public void syncInputTransactions() { events += "sync,"; }
}
''',
        "android/app/Instrumentation.java": '''
package android.app;
public class Instrumentation {
    public static boolean unavailable;
    public void waitForIdleSync() { UiAutomation.events += "idle,"; }
    public UiAutomation getUiAutomation(int flags) {
        if (flags != 1) throw new AssertionError("accessibility suppression");
        UiAutomation.events += "connect,";
        return unavailable ? null : new UiAutomation();
    }
}
''',
        "androidx/test/platform/app/InstrumentationRegistry.java": '''
package androidx.test.platform.app;
public class InstrumentationRegistry {
    public static android.app.Instrumentation getInstrumentation() {
        return new android.app.Instrumentation();
    }
}
''',
        "androidx/lifecycle/Lifecycle.java": '''
package androidx.lifecycle;
public class Lifecycle { public enum State { CREATED, RESUMED } }
''',
        "androidx/test/core/app/ActivityScenario.java": '''
package androidx.test.core.app;
public class ActivityScenario {
    public static ActivityScenario launch(Class<?> activity) {
        return new ActivityScenario();
    }
    public void close() {}
    public ActivityScenario moveToState(androidx.lifecycle.Lifecycle.State state) {
        android.app.UiAutomation.events += state + ",";
        return this;
    }
}
''',
        "Probe.java": '''
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.os.Build;
import org.pyjs.testing.PyjsAndroid;

public class Probe {
    private static void events(String expected) {
        if (!expected.equals(UiAutomation.events))
            throw new AssertionError(UiAutomation.events);
        UiAutomation.events = "";
    }
    public static void main(String[] args) {
        try {
            PyjsAndroid.resume();
            throw new AssertionError("resume accepted missing scenario");
        } catch (IllegalStateException expected) {}
        events("");
        PyjsAndroid.launch(Probe.class);
        PyjsAndroid.background();
        events("CREATED,");
        for (int api : new int[]{21, 28, 29, 35}) {
            Build.VERSION.SDK_INT = api;
            PyjsAndroid.resume();
            events(api < 29 ? "RESUMED," : "RESUMED,idle,connect,sync,");
        }
        Instrumentation.unavailable = true;
        try {
            PyjsAndroid.resume();
            throw new AssertionError("resume concealed unavailable input sync");
        } catch (IllegalStateException expected) {
            if (!expected.getMessage().contains("UiAutomation is unavailable"))
                throw new AssertionError(expected);
        }
        events("RESUMED,idle,connect,");
    }
}
''',
    }
    name, bytecode = espresso_android_class()
    bridge = tmp_path / (name + ".class")
    bridge.parent.mkdir(parents=True)
    bridge.write_bytes(bytecode)
    paths = []
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        paths.append(str(path))
    compiled = subprocess.run(
        [javac, "-cp", str(tmp_path), "-d", str(tmp_path), *paths],
        capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    result = subprocess.run(
        [java, "-Xverify:all", "-cp", str(tmp_path), "Probe"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
