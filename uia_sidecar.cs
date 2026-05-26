using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;

class UiaSidecar
{
    [DllImport("user32.dll")]
    static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")]
    static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    [DllImport("user32.dll")]
    static extern IntPtr PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")]
    static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")]
    static extern int EnumWindows(EnumWindowsProc lpEnumFunc, int lParam);
    [DllImport("user32.dll")]
    static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
    [DllImport("user32.dll")]
    static extern int GetWindowText(IntPtr hWnd, StringBuilder lpWindowText, int nMaxCount);
    delegate bool EnumWindowsProc(IntPtr hWnd, int lParam);
    const string WECHAT_CLASS = "Qt51514QWindowIcon";

    const uint WM_MOUSEWHEEL = 0x020A;
    const int WHEEL_DELTA = 120;
    const byte VK_RETURN = 0x0D;
    const uint KEYEVENTF_KEYUP = 0x0002;
    const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    const uint MOUSEEVENTF_LEFTUP = 0x0004;

    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;

        if (args.Length == 0)
        {
            Console.Error.WriteLine("Usage: uia_sidecar.exe <command> [args...]");
            Console.Error.WriteLine("  read              Read visible messages from current chat");
            Console.Error.WriteLine("  send <text>       Send message to current chat");
            Console.Error.WriteLine("  history <count>   Read history by scrolling up <count> times");
            Console.Error.WriteLine("  sessions          List all chat sessions");
            Console.Error.WriteLine("  switch <contact>  Switch to contact (experimental)");
            Console.Error.WriteLine("  dump [depth=3]    Dump UIA tree structure");
            Console.Error.WriteLine("  find <autoId>     Find element by AutomationId");
            return 1;
        }

        IntPtr hwnd = FindWeChatWindow();
        if (hwnd == IntPtr.Zero)
        {
            Console.Error.WriteLine("ERROR: WeChat window not found (tried titles: 微信, WeChat, 微信[0-9], class: Qt51514QWindowIcon)");
            return 1;
        }

        AutomationElement root = AutomationElement.FromHandle(hwnd);
        string cmd = args[0].ToLower();

        switch (cmd)
        {
            case "sessions":
                return ListSessions(root);
            case "read":
                return ReadMessages(root);
            case "send":
                if (args.Length < 2) { Console.Error.WriteLine("ERROR: missing text"); return 1; }
                return SendMessage(root, args[1]);
            case "history":
                int count = args.Length > 1 ? int.Parse(args[1]) : 20;
                return ReadHistory(root, hwnd, count);
            case "switch":
                if (args.Length < 2) { Console.Error.WriteLine("ERROR: missing contact"); return 1; }
                return SwitchChat(root, args[1]);
            case "dump":
                return DumpTree(root, args.Length > 1 ? int.Parse(args[1]) : 3);
            case "find":
                if (args.Length < 2) { Console.Error.WriteLine("ERROR: missing automationId"); return 1; }
                return FindElement(root, args[1]);
            default:
                Console.Error.WriteLine("ERROR: unknown command");
                return 1;
        }
    }

    // ══════════════════════════════════════════════════════
    //  COMMANDS
    // ══════════════════════════════════════════════════════

    static int ReadMessages(AutomationElement root)
    {
        var msgList = FindMessageList(root);
        if (msgList == null) return 1;
        var msgs = msgList.FindAll(TreeScope.Children, Condition.TrueCondition);
        OutputMessages(msgs);
        return 0;
    }

    static int ReadHistory(AutomationElement root, IntPtr hwnd, int scrollCount)
    {
        var msgList = FindMessageList(root);
        if (msgList == null) return 1;

        var msgRect = msgList.Current.BoundingRectangle;
        int scrollX = (int)(msgRect.Left + msgRect.Width / 2);
        int scrollY = (int)(msgRect.Top + msgRect.Height / 2);
        IntPtr wheelPos = (IntPtr)((scrollY << 16) | (scrollX & 0xFFFF));

        HashSet<string> seen = new HashSet<string>();
        List<string> allMsgs = new List<string>();
        CollectUniqueMessages(msgList, seen, allMsgs);

        int scrollsWithoutNew = 0;
        for (int i = 0; i < scrollCount && scrollsWithoutNew < 5; i++)
        {
            PostMessage(hwnd, WM_MOUSEWHEEL, (IntPtr)(WHEEL_DELTA << 16), wheelPos);
            System.Threading.Thread.Sleep(300);

            int before = allMsgs.Count;
            CollectUniqueMessages(msgList, seen, allMsgs);
            scrollsWithoutNew = (allMsgs.Count == before) ? scrollsWithoutNew + 1 : 0;
        }

        int scrollDown = Math.Max(scrollCount, 10) * 2;
        PostMessage(hwnd, WM_MOUSEWHEEL, (IntPtr)((-WHEEL_DELTA * scrollDown) << 16), wheelPos);
        System.Threading.Thread.Sleep(800);
        for (int i = 0; i < 3; i++)
        {
            PostMessage(hwnd, WM_MOUSEWHEEL, (IntPtr)((-WHEEL_DELTA) << 16), wheelPos);
            System.Threading.Thread.Sleep(200);
        }

        Console.WriteLine("COUNT:" + allMsgs.Count);
        for (int i = allMsgs.Count - 1; i >= 0; i--)
            Console.WriteLine((allMsgs.Count - 1 - i) + "\t" + allMsgs[i]);

        return 0;
    }

    static void CollectUniqueMessages(AutomationElement msgList, HashSet<string> seen, List<string> collected)
    {
        var msgs = msgList.FindAll(TreeScope.Children, Condition.TrueCondition);
        for (int i = msgs.Count - 1; i >= 0; i--)
        {
            string text = msgs[i].Current.Name.Replace('\n', ' ').Replace('\r', ' ').Trim();
            if (text.Length == 0) continue;
            string key = text.Length > 80 ? text.Substring(0, 80) : text;
            if (!seen.Contains(key))
            {
                seen.Add(key);
                collected.Add(text);
            }
        }
    }

    static int SendMessage(AutomationElement root, string text)
    {
        var input = FindInputField(root);
        if (input == null) { Console.Error.WriteLine("ERROR: input box not found"); return 1; }

        try { input.SetFocus(); } catch { }
        System.Threading.Thread.Sleep(100);

        try
        {
            ValuePattern vp = (ValuePattern)input.GetCurrentPattern(ValuePattern.Pattern);
            vp.SetValue(text);
        }
        catch (Exception ex) { Console.Error.WriteLine("ERROR: SetValue: " + ex.Message); return 1; }

        System.Threading.Thread.Sleep(300);

        var sendBtn = FindButton(root, "发送");

        if (sendBtn != null)
        {
            try
            {
                InvokePattern inv = (InvokePattern)sendBtn.GetCurrentPattern(InvokePattern.Pattern);
                inv.Invoke();
            }
            catch { }
        }

        System.Threading.Thread.Sleep(200);

        // Send Enter key
        keybd_event(VK_RETURN, 0, 0, UIntPtr.Zero);
        keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);

        System.Threading.Thread.Sleep(200);

        // Click send button at screen coordinates
        if (sendBtn != null)
        {
            try
            {
                var rect = sendBtn.Current.BoundingRectangle;
                int cx = (int)(rect.Left + rect.Width / 2);
                int cy = (int)(rect.Top + rect.Height / 2);
                mouse_event(MOUSEEVENTF_LEFTDOWN, cx, cy, 0, UIntPtr.Zero);
                mouse_event(MOUSEEVENTF_LEFTUP, cx, cy, 0, UIntPtr.Zero);
            }
            catch { }
        }

        System.Threading.Thread.Sleep(300);
        Console.WriteLine("SUCCESS");
        return 0;
    }

    static int ListSessions(AutomationElement root)
    {
        var list = FindSessionList(root);
        if (list == null) { Console.Error.WriteLine("ERROR: session_list not found"); return 1; }
        var sessions = list.FindAll(TreeScope.Children, Condition.TrueCondition);
        Console.WriteLine("COUNT:" + sessions.Count);
        for (int i = 0; i < sessions.Count; i++)
        {
            string firstLine = sessions[i].Current.Name.Split('\n')[0].Trim();
            Console.WriteLine(i + "\t" + firstLine);
        }
        return 0;
    }

    static int SwitchChat(AutomationElement root, string contactName)
    {
        var searchEdits = root.FindAll(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit));
        AutomationElement searchField = null;
        for (int i = 0; i < searchEdits.Count; i++)
        {
            if (searchEdits[i].Current.Name == "搜索")
            { searchField = searchEdits[i]; break; }
        }
        if (searchField == null)
        { Console.Error.WriteLine("ERROR: search field not found"); return 1; }

        try
        {
            ValuePattern vp = (ValuePattern)searchField.GetCurrentPattern(ValuePattern.Pattern);
            vp.SetValue(contactName);
        }
        catch (Exception ex)
        { Console.Error.WriteLine("ERROR: search SetValue: " + ex.Message); return 1; }

        System.Threading.Thread.Sleep(1500);

        var popups = root.FindAll(TreeScope.Descendants, new AndCondition(
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Window),
            new PropertyCondition(AutomationElement.ClassNameProperty, "mmui::SearchContentPopover")));
        AutomationElement searchWindow = popups.Count > 0 ? popups[0] : null;

        if (searchWindow != null)
        {
            var searchList = searchWindow.FindFirst(TreeScope.Descendants,
                new PropertyCondition(AutomationElement.AutomationIdProperty, "search_list"));
            if (searchList != null)
            {
                var items = searchList.FindAll(TreeScope.Children, Condition.TrueCondition);
                var match = FindMatchingItem(items, contactName);
                if (match != null)
                {
                    if (TrySelect(match)) goto success;
                    if (TryInvoke(match)) goto success;
                }
            }
        }

        var list = root.FindFirst(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.AutomationIdProperty, "session_list"));
        if (list != null)
        {
            var sessions = list.FindAll(TreeScope.Children, Condition.TrueCondition);
            var match2 = FindMatchingItem(sessions, contactName);
            if (match2 != null)
            {
                if (TrySelect(match2)) goto success;
                if (TryInvoke(match2)) goto success;
            }
        }

        Console.Error.WriteLine("ERROR: could not find/select contact");
        ClearSearch(searchField);
        return 1;

    success:
        System.Threading.Thread.Sleep(1000);
        ClearSearch(searchField);
        Console.WriteLine("SUCCESS");
        return 0;
    }

    static int FindElement(AutomationElement root, string autoId)
    {
        var el = root.FindFirst(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.AutomationIdProperty, autoId));
        if (el == null)
        {
            Console.Error.WriteLine("ERROR: element with AutomationId '" + autoId + "' not found");
            return 1;
        }
        Console.WriteLine("Found: CtlType={0} Name='{1}' Class='{2}' IsEnabled={3}",
            el.Current.ControlType.ProgrammaticName,
            el.Current.Name,
            el.Current.ClassName,
            el.Current.IsEnabled);
        var rect = el.Current.BoundingRectangle;
        Console.WriteLine("BoundingRect: ({0},{1}) {2}x{3}", (int)rect.Left, (int)rect.Top, (int)rect.Width, (int)rect.Height);
        return 0;
    }

    static int DumpTree(AutomationElement root, int maxDepth)
    {
        DumpElement(root, 0, maxDepth);
        return 0;
    }

    static void DumpElement(AutomationElement el, int depth, int maxDepth)
    {
        if (depth > maxDepth) return;
        string indent = new string(' ', depth * 2);
        string ctlType = el.Current.ControlType.ProgrammaticName;
        if (ctlType.StartsWith("ControlType.")) ctlType = ctlType.Substring(12);
        string name = el.Current.Name;
        string autoId = el.Current.AutomationId;
        string cls = el.Current.ClassName;
        if (name.Length > 60) name = name.Substring(0, 60) + "...";
        Console.WriteLine("{0}{1} id='{2}' name='{3}' class='{4}'", indent, ctlType, autoId, name, cls);
        try
        {
            var children = el.FindAll(TreeScope.Children, Condition.TrueCondition);
            for (int i = 0; i < children.Count; i++)
                DumpElement(children[i], depth + 1, maxDepth);
        }
        catch { }
    }

    // ══════════════════════════════════════════════════════
    //  HELPERS
    // ══════════════════════════════════════════════════════

    static IntPtr FindWeChatWindow()
    {
        // Try exact window titles first
        string[] titles = new string[] { "微信", "WeChat" };
        for (int i = 0; i < titles.Length; i++)
        {
            IntPtr hwnd = FindWindow(null, titles[i]);
            if (hwnd != IntPtr.Zero) return hwnd;
        }

        // Fallback: enumerate all windows and check by class name
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate (IntPtr hwnd, int param)
        {
            StringBuilder cls = new StringBuilder(256);
            GetClassName(hwnd, cls, 256);
            if (cls.ToString() == WECHAT_CLASS)
            {
                found = hwnd;
                return false; // stop enumeration
            }
            return true;
        }, 0);

        return found;
    }

    static AutomationElement FindMessageList(AutomationElement root)
    {
        // Strategy 1: direct AutomationId match (WeChat 4.x standard)
        var list = root.FindFirst(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.AutomationIdProperty, "chat_message_list"));
        if (list != null) return list;

        // Strategy 2: try common alternative IDs across WeChat versions
        string[] altIds = new string[] { "chat_list", "message_list", "msg_list", "ChatHistory" };
        for (int i = 0; i < altIds.Length; i++)
        {
            list = root.FindFirst(TreeScope.Descendants,
                new PropertyCondition(AutomationElement.AutomationIdProperty, altIds[i]));
            if (list != null) return list;
        }

        // Strategy 3: find any List-type element with text content
        var lists = root.FindAll(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.List));
        for (int i = 0; i < lists.Count; i++)
        {
            var kids = lists[i].FindAll(TreeScope.Children, Condition.TrueCondition);
            if (kids.Count >= 2)
            {
                // Check if children have text content (likely messages)
                for (int j = 0; j < kids.Count; j++)
                {
                    if (kids[j].Current.Name.Length > 0)
                        return lists[i];
                }
            }
        }

        // Strategy 4: walk full tree looking for deepest Custom with many text children
        AutomationElement deepest = null;
        int deepestCount = 0;
        WalkForMessageArea(root, 0, ref deepest, ref deepestCount);

        Console.Error.WriteLine("ERROR: message list not found (tried automation ids, List controls, tree walk)");
        return null;
    }

    static AutomationElement FindInputField(AutomationElement root)
    {
        // Strategy 1: AutomationId match
        var el = root.FindFirst(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.AutomationIdProperty, "chat_input_field"));
        if (el != null) return el;

        // Strategy 2: ClassName match (WeChat 4.x mmui)
        var edits = root.FindAll(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit));
        for (int i = 0; i < edits.Count; i++)
        {
            string cls = edits[i].Current.ClassName;
            if (cls != null && cls.IndexOf("ChatInput", StringComparison.OrdinalIgnoreCase) >= 0)
                return edits[i];
        }

        // Strategy 3: find the largest Edit near bottom-right (most likely input field)
        AutomationElement best = null;
        double bestArea = 0;
        for (int i = 0; i < edits.Count; i++)
        {
            var rect = edits[i].Current.BoundingRectangle;
            double area = rect.Width * rect.Height;
            if (area > bestArea) { bestArea = area; best = edits[i]; }
        }
        if (best != null) return best;

        return null;
    }

    static AutomationElement FindSessionList(AutomationElement root)
    {
        // Strategy 1: AutomationId match
        var list = root.FindFirst(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.AutomationIdProperty, "session_list"));
        if (list != null) return list;

        // Strategy 2: Find a List control with many children (session items)
        var lists = root.FindAll(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.List));
        for (int i = 0; i < lists.Count; i++)
        {
            if (lists[i].FindAll(TreeScope.Children, Condition.TrueCondition).Count >= 2)
                return lists[i];
        }

        // Strategy 3: Tree walk looking for a Group/Custom with 5+ named children
        AutomationElement best = null;
        int bestCount = 0;
        WalkForSessionList(root, 0, 6, ref best, ref bestCount);
        if (best != null) return best;

        return null;
    }

    static void WalkForSessionList(AutomationElement el, int depth, int maxDepth, ref AutomationElement best, ref int bestCount)
    {
        if (depth > maxDepth) return;
        try
        {
            var children = el.FindAll(TreeScope.Children, Condition.TrueCondition);
            if (children.Count >= 3)
            {
                int namedCount = 0;
                for (int i = 0; i < children.Count; i++)
                    if (children[i].Current.Name.Length > 0) namedCount++;
                if (namedCount > bestCount)
                {
                    bestCount = namedCount;
                    best = el;
                }
            }
            for (int i = 0; i < children.Count; i++)
                WalkForSessionList(children[i], depth + 1, maxDepth, ref best, ref bestCount);
        }
        catch { }
    }

    static void WalkForMessageArea(AutomationElement el, int depth, ref AutomationElement best, ref int bestCount)
    {
        if (depth > 8) return;
        try
        {
            var children = el.FindAll(TreeScope.Children, Condition.TrueCondition);
            if (children.Count >= 3)
            {
                int textCount = 0;
                for (int i = 0; i < children.Count; i++)
                    if (children[i].Current.Name.Length > 0) textCount++;
                if (textCount > bestCount)
                {
                    bestCount = textCount;
                    best = el;
                }
            }
            for (int i = 0; i < children.Count; i++)
                WalkForMessageArea(children[i], depth + 1, ref best, ref bestCount);
        }
        catch { }
    }

    static void OutputMessages(AutomationElementCollection msgs)
    {
        Console.WriteLine("COUNT:" + msgs.Count);
        for (int i = 0; i < msgs.Count; i++)
        {
            string text = msgs[i].Current.Name.Replace('\n', ' ').Replace('\r', ' ').Trim();
            Console.WriteLine(i + "\t" + text);
        }
    }

    static AutomationElement FindButton(AutomationElement root, string name)
    {
        try
        {
            return root.FindFirst(TreeScope.Descendants, new AndCondition(
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Button),
                new PropertyCondition(AutomationElement.NameProperty, name)));
        }
        catch { return null; }
    }

    static AutomationElement FindMatchingItem(AutomationElementCollection items, string name)
    {
        for (int i = 0; i < items.Count; i++)
        {
            string firstLine = items[i].Current.Name.Split('\n')[0].Trim();
            if (firstLine.Contains(name) || name.Contains(firstLine))
                return items[i];
        }
        return null;
    }

    static bool TrySelect(AutomationElement el)
    {
        try { var s = el.GetCurrentPattern(SelectionItemPattern.Pattern) as SelectionItemPattern; if (s != null) { s.Select(); return true; } } catch { }
        return false;
    }

    static bool TryInvoke(AutomationElement el)
    {
        try { var s = el.GetCurrentPattern(InvokePattern.Pattern) as InvokePattern; if (s != null) { s.Invoke(); return true; } } catch { }
        return false;
    }

    static void ClearSearch(AutomationElement searchField)
    {
        try { ValuePattern vp = (ValuePattern)searchField.GetCurrentPattern(ValuePattern.Pattern); vp.SetValue(""); } catch { }
    }
}
