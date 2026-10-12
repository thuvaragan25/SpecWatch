from specwatch.tests_index.pytest_parser import extract_test_symbols, is_test_file


def test_is_test_file() -> None:
    assert is_test_file("test_foo.py")
    assert is_test_file("foo_test.py")
    assert not is_test_file("foo.py")
    assert not is_test_file("conftest.py")


def test_top_level_test_function_is_extracted() -> None:
    source = "def test_something():\n    assert True\n"
    tests = extract_test_symbols(source, file="test_a.py", module_name="tests.test_a")
    assert len(tests) == 1
    assert tests[0].qualified_name == "tests.test_a.test_something"


def test_non_test_function_is_ignored() -> None:
    source = "def helper():\n    pass\n\n\ndef test_real():\n    assert True\n"
    tests = extract_test_symbols(source, file="test_a.py", module_name="tests.test_a")
    assert [t.name for t in tests] == ["test_real"]


def test_class_based_tests_are_extracted() -> None:
    source = (
        "class TestFoo:\n"
        "    def test_one(self):\n"
        "        assert True\n"
        "    def helper(self):\n"
        "        pass\n"
        "\n"
        "class NotATestClass:\n"
        "    def test_ignored(self):\n"
        "        assert True\n"
    )
    tests = extract_test_symbols(source, file="test_a.py", module_name="tests.test_a")
    assert [t.qualified_name for t in tests] == ["tests.test_a.TestFoo.test_one"]


def test_fixtures_are_parameter_names_excluding_self() -> None:
    source = "def test_thing(tmp_path, monkeypatch):\n    assert tmp_path\n"
    tests = extract_test_symbols(source, file="test_a.py", module_name="tests.test_a")
    assert tests[0].fixtures == ["tmp_path", "monkeypatch"]


def test_assertions_are_extracted_as_condition_text() -> None:
    source = (
        "def test_thing():\n"
        "    x = 1\n"
        "    assert x == 1\n"
        "    assert x > 0, 'should be positive'\n"
    )
    tests = extract_test_symbols(source, file="test_a.py", module_name="tests.test_a")
    assert tests[0].assertions == ["x == 1", "x > 0"]


def test_docstring_is_captured() -> None:
    source = 'def test_thing():\n    """Explains the test."""\n    assert True\n'
    tests = extract_test_symbols(source, file="test_a.py", module_name="tests.test_a")
    assert tests[0].docstring == "Explains the test."
