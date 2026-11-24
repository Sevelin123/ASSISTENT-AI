/*
  J.A.R.V.I.S. desktop launcher.

  Compiled by windows/setup.ps1 into JARVIS-APP.exe with the .NET Framework
  compiler that ships with Windows. It starts the local Python server hidden
  and opens a standalone Edge/Chrome app-mode window: no tabs, no address bar,
  no browser toolbar. No Arena key, no cloud key and no external dependency.
*/

using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows.Forms;

internal static class JarvisDesktop
{
    private static int Port = 8080;

    private class PythonInfo
    {
        public string Path;
        public string Prefix;
    }

    private static string HudUrl()
    {
        return "http://127.0.0.1:" + Port.ToString();
    }

    private static int ParsePort(string[] args)
    {
        if (args != null)
        {
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i] ?? "";
                int p;
                if (a.StartsWith("--port=", StringComparison.OrdinalIgnoreCase) &&
                    int.TryParse(a.Substring(7), out p) && p > 0 && p < 65536)
                    return p;
                if ((a == "-Port" || a == "--port") && i + 1 < args.Length &&
                    int.TryParse(args[i + 1], out p) && p > 0 && p < 65536)
                    return p;
            }
        }
        return 8080;
    }

    private static bool Healthy()
    {
        try
        {
            HttpWebRequest req = (HttpWebRequest)WebRequest.Create(HudUrl() + "/api/health");
            req.Method = "GET";
            req.Timeout = 700;
            req.ReadWriteTimeout = 700;
            req.Proxy = null;              // never send loopback through a corporate proxy
            req.KeepAlive = false;
            using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
            {
                return resp.StatusCode == HttpStatusCode.OK;
            }
        }
        catch
        {
            return false;
        }
    }

    private static bool WaitHealthy()
    {
        for (int i = 0; i < 40; i++)
        {
            if (Healthy()) return true;
            Thread.Sleep(500);
        }
        return false;
    }

    private static string FindOnPath(string exe)
    {
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo("where.exe", exe);
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.RedirectStandardOutput = true;
            Process p = Process.Start(psi);
            if (p == null) return null;
            using (p)
            {
                string output = p.StandardOutput.ReadToEnd();
                p.WaitForExit();
                string[] lines = output.Split(new char[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                foreach (string line in lines)
                {
                    string candidate = line.Trim().Trim('"');
                    if (File.Exists(candidate)) return candidate;
                }
            }
        }
        catch
        {
        }
        return null;
    }

    private static PythonInfo FindPython()
    {
        string[] names = new string[] { "pyw.exe", "pythonw.exe", "py.exe", "python.exe" };
        foreach (string name in names)
        {
            string found = FindOnPath(name);
            if (found != null)
            {
                PythonInfo info = new PythonInfo();
                info.Path = found;
                info.Prefix = name.StartsWith("py", StringComparison.OrdinalIgnoreCase) ? "-3 " : "";
                return info;
            }
        }
        return null;
    }

    private static Process StartServer(string appDir)
    {
        if (Healthy()) return null;
        PythonInfo py = FindPython();
        if (py == null)
        {
            MessageBox.Show(
                "Python 3.9+ не найден. Запустите INSTALL_WINDOWS.bat ещё раз.",
                "J.A.R.V.I.S.", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return null;
        }
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = py.Path;
            psi.Arguments = py.Prefix + "jarvis.py --smart --host 127.0.0.1 --port " + Port.ToString();
            psi.WorkingDirectory = appDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            return Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("Не удалось запустить локальный сервер: " + ex.Message,
                "J.A.R.V.I.S.", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return null;
        }
    }

    private static string FindBrowser()
    {
        string pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string pf86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)");
        if (String.IsNullOrEmpty(pf86)) pf86 = pf;
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

        string[] candidates = new string[]
        {
            Path.Combine(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
            Path.Combine(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            Path.Combine(local, "Microsoft", "Edge", "Application", "msedge.exe"),
            Path.Combine(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            Path.Combine(pf, "Google", "Chrome", "Application", "chrome.exe"),
            Path.Combine(local, "Google", "Chrome", "Application", "chrome.exe"),
        };
        foreach (string candidate in candidates)
        {
            if (File.Exists(candidate)) return candidate;
        }
        string onPath = FindOnPath("msedge.exe");
        if (onPath == null) onPath = FindOnPath("chrome.exe");
        return onPath;
    }

    private static bool LaunchApp(string baseDir)
    {
        string browser = FindBrowser();
        if (browser == null)
        {
            MessageBox.Show(
                "Нужен Microsoft Edge или Google Chrome для голосового Web Speech API. " +
                "Установите Edge и запустите JARVIS-APP.exe снова.",
                "J.A.R.V.I.S.", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return false;
        }
        string profile = Path.Combine(baseDir, "DesktopProfile");
        try { Directory.CreateDirectory(profile); } catch { }

        string args =
            "--app=" + HudUrl() +
            " --user-data-dir=\"" + profile + "\"" +
            " --window-size=1440,900 --window-position=40,40" +
            " --no-first-run --no-default-browser-check --disable-extensions --disable-sync" +
            " --disable-features=msEdgeSplitScreen,msWebOOUI,msPdfOOUI" +
            " --proxy-bypass-list=\"127.0.0.1;localhost\"";

        ProcessStartInfo psi = new ProcessStartInfo(browser, args);
        psi.UseShellExecute = true;
        psi.WindowStyle = ProcessWindowStyle.Normal;
        Process.Start(psi);
        return true;
    }

    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Port = ParsePort(args);
        string baseDir = Path.GetDirectoryName(Application.ExecutablePath);
        string appDir = Path.Combine(baseDir, "app");
        if (!File.Exists(Path.Combine(appDir, "jarvis.py"))) appDir = baseDir;

        try
        {
            StartServer(appDir);
            if (!WaitHealthy())
            {
                MessageBox.Show(
                    "Локальный сервер не ответил за 20 секунд. " +
                    "Проверьте START-JARVIS.bat или FIX-SERVER.bat.",
                    "J.A.R.V.I.S.", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            LaunchApp(baseDir);
        }
        catch (Exception ex)
        {
            MessageBox.Show("Ошибка запуска приложения: " + ex.Message,
                "J.A.R.V.I.S.", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
