"""CLI session, relative paths, and the odag-style stream (pipe/interactive)
mode — exercised offline by injecting the zoo filesystem into a Session."""

from __future__ import annotations

import io

from ontodag_fs.__main__ import Session, dispatch, run_stream


def make_session(zoo) -> Session:
    session = Session(None, None)
    session._fs = zoo.fs  # bypass store loading; the session logic is under test
    return session


def test_resolve_relative_absolute_and_dotdot(zoo):
    session = make_session(zoo)
    assert session.resolve("pet") == "/pet"
    assert session.resolve("/pet/dog") == "/pet/dog"
    session.cwd = "/pet/mammal"
    assert session.resolve("dog") == "/pet/mammal/dog"
    assert session.resolve("..") == "/pet"
    assert session.resolve("../..") == "/"
    assert session.resolve(".") == "/pet/mammal"
    assert session.resolve("/") == "/"


def test_cd_pwd_and_relative_commands(zoo, capsys):
    session = make_session(zoo)
    assert dispatch(["cd", "pet"], session) == 0
    assert session.cwd == "/pet"
    assert dispatch(["cd", "mammal/dog"], session) == 0
    assert session.cwd == "/pet/mammal/dog"
    assert dispatch(["pwd"], session) == 0
    assert dispatch(["ls"], session) == 0
    out = capsys.readouterr().out
    assert "/pet/mammal/dog" in out
    assert "rex.jpg" in out


def test_cd_to_file_or_unknown_fails(zoo, capsys):
    session = make_session(zoo)
    assert dispatch(["cd", "unicorn"], session) == 1
    assert session.cwd == "/"
    assert "odag-fs:" in capsys.readouterr().err


def test_batch_stream_continues_after_errors(zoo, capsys):
    session = make_session(zoo)
    script = io.StringIO(
        "# a comment\n"
        "\n"
        "cd pet\n"
        "pwd\n"
        "ls /unicorn\n"          # fails — loop must continue
        "cat mammal/dog/rex.jpg\n"
        "exit\n"
        "pwd\n"                   # never reached
    )
    code = run_stream(session, script, interactive=False)
    captured = capsys.readouterr()
    assert code == 1  # a batch with a failing line exits non-zero
    assert "/pet\n" in captured.out
    assert "rex the dog" in captured.out
    assert captured.out.count("/pet\n") == 1  # exit stopped the stream
    assert "odag-fs:" in captured.err


def test_batch_stream_all_good_exits_zero(zoo, capsys):
    session = make_session(zoo)
    code = run_stream(session, io.StringIO("ls /\nquit\n"), interactive=False)
    assert code == 0
    assert "animal/" in capsys.readouterr().out
