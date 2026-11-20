"""IPC boundary for the packaged app's isolated native notification presenter."""
from pyjs import js


@js
def main() -> None: ...


main.source(r"""
const {app, Notification} = require('electron');
if (!process.send) throw new Error('Notification worker requires parent IPC');
const items = new Map();
const send = message => {
    try {
        if (process.connected) process.send(message, error => {if (error) app.exit(1)});
    } catch {app.exit(1)}
};
const reply = (id, value = null, error = '') => send({event: 'reply', id, value, error});
process.on('disconnect', () => app.exit());
process.on('message', message => {
    try {
        if (message.operation === 'identity') {
            app.setName(message.name);
            app.setAppUserModelId(message.application_id);
            if (process.platform === 'linux') app.setDesktopName(message.desktop_name);
        } else if (message.operation === 'support') {
            reply(message.id, Notification.isSupported());
        } else if (message.operation === 'close') {
            const item = items.get(message.key);
            if (item) {
                items.delete(message.key);
                item.notification.removeAllListeners();
                item.notification.close();
                if (!item.shown) reply(item.id, null, 'Notification closed before publication');
            }
            reply(message.id);
        } else if (message.operation === 'show') {
            if (!Notification.isSupported()) throw new Error('Desktop notifications are unavailable');
            if (items.has(message.key) || items.size >= 128) throw new Error('Notification service is full');
            const notification = new Notification(message.options);
            const item = {notification, id: message.id, shown: false};
            items.set(message.key, item);
            notification.on('show', () => {
                if (!item.shown) {item.shown = true; reply(message.id)}
            });
            notification.on('failed', (_event, error) => {
                if (!item.shown) reply(message.id, null, error || 'Notification publication failed');
            });
            notification.on('close', () => {
                if (!item.shown) reply(message.id, null, 'Notification closed before publication');
            });
            notification.on('click', () => send({event: 'click', key: message.key, id: message.id}));
            notification.show();
        } else {
            throw new Error('Unknown notification operation');
        }
    } catch (error) {reply(message.id, null, String(error.message || error))}
});
app.whenReady().then(() => {
    if (app.dock) app.dock.hide();
    send({event: 'ready'});
}).catch(() => app.exit(1));
""")
