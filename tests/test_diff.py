from reviewer.diff import make_diff, parse_unified_diff, render_for_llm

GIT_DIFF = """diff --git a/app/x.py b/app/x.py
index 111..222 100644
--- a/app/x.py
+++ b/app/x.py
@@ -1,4 +1,5 @@
 import os
-A = 1
+A = 2
+B = 3

 def f():
@@ -10,3 +11,3 @@ def g():
     x = 1
-    return x
+    return x + 1
 # end
diff --git a/app/new.py b/app/new.py
new file mode 100644
--- /dev/null
+++ b/app/new.py
@@ -0,0 +1,2 @@
+print("hi")
+print("bye")
diff --git a/app/gone.py b/app/gone.py
deleted file mode 100644
--- a/app/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
"""


def test_parses_files_and_skips_deleted():
    files = parse_unified_diff(GIT_DIFF)
    assert [f.path for f in files] == ["app/x.py", "app/new.py"]
    assert files[1].is_new


def test_added_and_commentable_lines():
    x = parse_unified_diff(GIT_DIFF)[0]
    assert x.added_lines == {2, 3, 12}
    assert x.commentable_lines == set(range(1, 6)) | set(range(11, 14))


def test_render_numbers_new_side():
    out = render_for_llm(parse_unified_diff(GIT_DIFF))
    assert "    2 + A = 2" in out
    assert "      - A = 1" in out
    assert "### app/new.py (new file)" in out


def test_make_diff_roundtrip():
    d = make_diff("a.py", "x = 1\ny = 2\n", "x = 1\ny = 3\nz = 4\n")
    f = parse_unified_diff(d)[0]
    assert f.path == "a.py" and f.added_lines == {2, 3}


def test_make_diff_new_file():
    f = parse_unified_diff(make_diff("n.py", None, "a\nb\n"))[0]
    assert f.is_new and f.added_lines == {1, 2}
