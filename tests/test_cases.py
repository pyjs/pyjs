from tests.utils import BaseTestCase


class FunctionalTestCases(BaseTestCase):

    def test_boolean(self):
        self.analyze_file("type_boolean")
        self.transpile_file("type_boolean")

    def test_numbers(self):
        self.analyze_file("type_numbers")
        self.transpile_file("type_numbers")

    def test_strings(self):
        self.analyze_file("type_strings")
        self.transpile_file("type_strings")

    def test_lists(self):
        self.analyze_file("type_lists")
        self.transpile_file("type_lists")

    def test_dicts(self):
        self.analyze_file("type_dicts")
        self.transpile_file("type_dicts")

    def test_classes(self):
        self.analyze_file("classes", no_assert=True)
        self.transpile_file("classes", no_assert=True)

    def test_inference(self):
        self.analyze_file("inference", no_assert=True)
        self.transpile_file("inference", no_assert=True)

    def test_attrs(self):
        self.analyze_file('attrs')
        self.transpile_file('attrs')

    def test_generics(self):
        self.analyze_file('generics')
        self.transpile_file("generics", no_assert=True)
