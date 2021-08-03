from pyjamas.ui.Label import Label
from pyjamas.ui.RootPanel import RootPanel
from pyjamas.ui.VerticalPanel import VerticalPanel
from pyjamas.ui.TextBox import TextBox
from pyjamas.ui.ListBox import ListBox
from pyjamas.ui import KeyboardListener

from pyjamas.JSONService import JSONProxy

class TodoApp:
    def onModuleLoad(self):
        self.remote = DataService()
        panel = VerticalPanel()

        self.todoTextBox = TextBox()
        self.todoTextBox.addKeyboardListener(self)

        self.todoList = ListBox()
        self.todoList.setVisibleItemCount(7)
        self.todoList.setWidth("200px")
        self.todoList.addClickListener(self)

        panel.add(Label("Add New Todo:"))
        panel.add(self.todoTextBox)
        panel.add(Label("Click to Remove:"))
        panel.add(self.todoList)

        self.status = Label()
        panel.add(self.status)

        RootPanel().add(panel)



    def onKeyUp(self, sender, keyCode, modifiers):
        pass

    def onKeyDown(self, sender, keyCode, modifiers):
        pass

    def onKeyPress(self, sender, keyCode, modifiers):
        """
        This function handles the onKeyPress event, and will add the item in the text box to the list when the user presses the enter key.  In the future, this method will also handle the auto complete feature.
        """
        if keyCode == KeyboardListener.KEY_ENTER and sender == self.todoTextBox:
            id = self.remote.addTask(sender.getText(),self)
            sender.setText("")

            if id<0:
                self.status.setText("Server Error or Invalid Response")


    def onClick(self, sender):
        id = self.remote.deleteTask(sender.getValue(sender.getSelectedIndex()),self)
        if id<0:
            self.status.setText("Server Error or Invalid Response")

    def onRemoteResponse(self, response, request_info):
        self.status.setText("response received")
        if request_info.method == 'getTasks' or request_info.method == 'addTask' or request_info.method == 'deleteTask':
            self.status.setText(self.status.getText() + "HERE!")
            self.todoList.clear()
            for task in response:
                self.todoList.addItem(task[0])
                self.todoList.setValue(self.todoList.getItemCount()-1,task[1])
        else:
            self.status.setText(self.status.getText() + "none!")

    def onRemoteError(self, code, errobj, request_info):
        message = errobj['message']
        self.status.setText("Server Error or Invalid Response: ERROR %s - %s" % (code, message))

class DataService(JSONProxy):
    def __init__(self):
        JSONProxy.__init__(self, "/services/", ["getTasks", "addTask","deleteTask"])

if __name__ == "__main__":
    app = TodoApp()
    app.onModuleLoad()

