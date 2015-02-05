import os

import sublime
from sublime_plugin import WindowCommand, TextCommand, EventListener

from .base_command import BaseCommand


DIFF_TITLE = "DIFF: {}"
DIFF_CACHED_TITLE = "DIFF (cached): {}"


class GgDiffCommand(WindowCommand, BaseCommand):

    def run(self, in_cached_mode=False):
        repo_path = self.repo_path
        diff_view = self.get_read_only_view("diff")
        title = (DIFF_CACHED_TITLE if in_cached_mode else DIFF_TITLE).format(os.path.basename(repo_path))
        diff_view.set_name(title)
        diff_view.set_syntax_file("Packages/Diff/Diff.tmLanguage")
        diff_view.settings().set("git_gadget.repo_path", repo_path)
        diff_view.settings().set("git_gadget.diff_view.in_cached_mode", in_cached_mode)
        self.window.focus_view(diff_view)
        diff_view.sel().clear()
        diff_view.run_command("gg_diff_refresh")


class GgDiffRefreshCommand(TextCommand, BaseCommand):

    def run(self, edit, cursors=None):
        in_cached_mode = self.view.settings().get("git_gadget.diff_view.in_cached_mode")
        stdout = self.git("diff", "--cached" if in_cached_mode else None)

        self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), stdout)
        self.view.set_read_only(True)

        if not len(self.view.sel()):
            self.view.sel().add(sublime.Region(0, 0))


class GgDiffFocusEventListener(EventListener):

    """
    If the current view is a diff view, refresh the view with latest tree status
    when the view regains focus.
    """

    def on_activated(self, view):
        if view.settings().get("git_gadget.diff_view") == True:
            # cursors = view.sel()
            view.run_command("gg_diff_refresh")
            # view.run_command("gg_diff_refresh", {"cursors": cursors})


class GgDiffStageOrResetHunkCommand(TextCommand, BaseCommand):

    def run(self, edit, reset=False):
        in_cached_mode = self.view.settings().get("git_gadget.diff_view.in_cached_mode")

        # Filter out any cursors that are larger than a single point.
        cursor_pts = tuple(cursor.a for cursor in self.view.sel() if cursor.a == cursor.b)

        self.diff_starts = tuple(region.a for region in self.view.find_all("^diff"))
        self.diff_header_ends = tuple(region.b for region in self.view.find_all("^\+\+\+.+\n(?=@@)"))
        self.hunk_starts = tuple(region.a for region in self.view.find_all("^@@"))
        hunk_starts_following_headers = {region.b for region in self.view.find_all("^\+\+\+.+\n(?=@@)")}
        self.hunk_ends = sorted(list(
            # Hunks end when the next diff starts.
            set(self.diff_starts[1:]) |
            # Hunks end when the next hunk starts, except for hunks
            # immediately following diff headers.
            (set(self.hunk_starts) - hunk_starts_following_headers) |
            # The last hunk ends at the end of the file.
            set((self.view.size(), ))
            ))

        # Apply the diffs in reverse order - otherwise, line number will be off.
        for pt in reversed(cursor_pts):
            hunk_diff = self.get_hunk_diff(pt)

            # The three argument combinations below result from the following
            # three scenarios:
            #
            # 1) The user is in non-cached mode and wants to stage a hunk, so
            #    do NOT apply the patch in reverse, but do apply it only against
            #    the cached/indexed file (not the working tree).
            # 2) The user is in non-cached mode and wants to undo a line/hunk, so
            #    DO apply the patch in reverse, and do apply it both against the
            #    index and the working tree.
            # 3) The user is in cached mode and wants to undo a line hunk, so DO
            #    apply the patch in reverse, but only apply it against the cached/
            #    indexed file.
            #
            # NOTE: When in cached mode, no action will be taken when the user
            #       presses SUPER-BACKSPACE.

            self.git(
                "apply",
                "-R" if (reset or in_cached_mode) else None,
                "--cached" if (in_cached_mode or not reset) else None,
                "-",
                stdin=hunk_diff
            )

        self.view.run_command("gg_diff_refresh")

    def get_hunk_diff(self, pt):
        header_start = self.get_pt_before(self.diff_starts, pt)
        header_end = self.get_pt_before(self.diff_header_ends, pt)

        if not header_end or header_end < header_start:
            # The cursor is not within a hunk.
            return

        diff_start = self.get_pt_before(self.hunk_starts, pt)
        diff_end = self.get_pt_after(self.hunk_ends, pt)

        header = self.view.substr(sublime.Region(header_start, header_end))
        diff = self.view.substr(sublime.Region(diff_start, diff_end))

        return header + diff

    @staticmethod
    def get_pt_before(candidates, pt):
        for candidate in reversed(candidates):
            if candidate <= pt:
                return candidate
        return None

    @staticmethod
    def get_pt_after(candidates, pt):
        for candidate in candidates:
            if candidate > pt:
                return candidate
        return None