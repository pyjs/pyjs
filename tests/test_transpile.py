from tests.utils import BaseTestCase


class TestTranspileConditionals(BaseTestCase):

    def test_basic_conditionals(self):
        self.t(
            """
            @js
            def main():
                a = 9
                if a == 9:
                    print('a is 9')
                elif a:
                    print('a has value')
                else:
                    print('no value')
            """,
            """
            // _test_
            
            function main() {
                var a = 9;
                if (a == 9) {
                    console.log('a is 9');
                } else if (a) {
                    console.log('a has value');
                } else {
                    console.log('no value');
                }
            }
            """
        )


class TestTranspileLoops(BaseTestCase):

    def test_basic_for_loop(self):
        self.t(
            """
            @js
            def main():
                l = ["a", "b", "c"]
                for i in l:
                    print(i)
            """,
            """
            // _test_
            
            function main() {
                var l = ['a', 'b', 'c'];
                for (var i in l) {
                    console.log(i);
                }
            }
            """
        )
