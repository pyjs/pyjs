from pyjs.testing.helpers import assert_transpile


def test_model_form_meta_generates_additive_widgets_and_hidden_id():
    assert_transpile(
        """
        from pydantic import BaseModel
        from pyjs.web.ui.model import ModelForm, TextModelField

        @js
        class Task(BaseModel):
            id: int | None = None
            title: str
            completed: bool = False

        @js
        class TaskForm(ModelForm[Task]):
            title = TextModelField(label="Task")

            class Meta:
                fields = ("completed",)

        def main():
            form = TaskForm(Task(id=7, title="Ship"))
            task = form.read_model()
            print(task.title)
        """,
        """
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { ModelForm, TextModelField, IntegerModelField, BooleanModelField } from './pyjs.web.ui.model.js';

        export class Task extends BaseModel {
        }
        Task.__pyjs_defaults__ = new Map([['id', null], ['completed', false]]);
        Task.__pyjs_required__ = ['title'];
        Task.__pyjs_fields__ = new Map([['id', ['union', 'int', 'NoneType']], ['title', 'str'], ['completed', 'bool']]);

        export class TaskForm extends ModelForm {
        }
        TaskForm.__pyjs_model__ = Task;
        TaskForm.__pyjs_fields__ = [new IntegerModelField({label: 'id', name: 'id', required: false, nullable: true, hidden: true}), new TextModelField({label: 'Task', name: 'title', required: true, max_length: 0, hidden: false}), new BooleanModelField({label: 'completed', name: 'completed', required: false})];
        TaskForm.__pyjs_model_fields__ = ['id', 'title', 'completed'];
        TaskForm.__pyjs_fields_by_name__ = new Map(TaskForm.__pyjs_fields__.map(field => [field.name, field]));

        export function main() {
            var form = new TaskForm()._create({model: new Task({id: 7, title: 'Ship'})});
            var task = form.read_model();
            console.log(task.title);
        }
        """,
    )
