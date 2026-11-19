"""The same native SQLite contract runs under Robolectric and on a device."""
import pytest

from pyjs.android.sqlite import (
    DatabaseErrorHandler,
    SQLiteConstraintException,
    SQLiteDatabase,
    SQLiteDatabaseCorruptException,
    SQLiteDoneException,
    SQLiteException,
    open_database,
)
from pyjs.android.testing import application_context
from pyjs.java import JVMArray, i32
from pyjs.java.io import RandomAccessFile, create_temp_file

pytestmark = pytest.mark.pyjs_android_jvm


class PreserveCorruptDatabase(DatabaseErrorHandler):
    def __init__(self):
        self.calls = 0
        self.path = ""

    def onCorruption(self, database: SQLiteDatabase) -> None:
        self.calls += 1
        self.path = database.getPath()
        raise SQLiteDatabaseCorruptException("Preserved corrupt database")


def test_corrupt_database_is_not_replaced_when_open_is_refused() -> None:
    file = create_temp_file("sqlite-corruption", ".db", application_context().getFilesDir())
    original = "Damaged database bytes retained for recovery. " * 128
    try:
        writer = RandomAccessFile(file.getPath(), "rw")
        try:
            writer.writeBytes(original)
            writer.getFD().sync()
        finally:
            writer.close()
        handler = PreserveCorruptDatabase()
        for attempt in range(2):
            rejected = False
            try:
                database = open_database(file.getPath(), None, handler)
                database.close()
            except SQLiteDatabaseCorruptException:
                rejected = True
            assert rejected, "A corrupt database must not be replaced by an empty one"
            assert handler.calls == attempt + 1
            assert handler.path == file.getPath()
            assert file.length() == len(original)
            reader = RandomAccessFile(file.getPath(), "r")
            try:
                assert reader.readLine() == original
                assert reader.readLine() is None
            finally:
                reader.close()
    finally:
        assert file.delete()


def test_custom_handler_keeps_healthy_creation_reopen_and_sql_errors() -> None:
    file = create_temp_file("sqlite-handler", ".db", application_context().getFilesDir())
    handler = PreserveCorruptDatabase()
    try:
        database = open_database(file.getPath(), None, handler)
        try:
            database.execSQL("CREATE TABLE records (value TEXT)")
            database.execSQL("INSERT INTO records VALUES ('retained')")
        finally:
            database.close()
        database = open_database(file.getPath(), None, handler)
        try:
            statement = database.compileStatement("SELECT value FROM records")
            try:
                assert statement.simpleQueryForString() == "retained"
            finally:
                statement.close()
            failed = False
            try:
                database.execSQL("INSERT INTO missing_table VALUES ('rejected')")
            except SQLiteException:
                failed = True
            assert failed and handler.calls == 0
        finally:
            database.close()
    finally:
        assert file.delete()


def test_statement_corruption_uses_the_registered_handler_without_deleting_file() -> None:
    file = create_temp_file("sqlite-query-corruption", ".db", application_context().getFilesDir())
    handler = PreserveCorruptDatabase()
    try:
        database = open_database(file.getPath(), None, handler)
        try:
            database.execSQL("CREATE TABLE records (value TEXT)")
            database.execSQL("INSERT INTO records VALUES ('retained')")
            # A valid schema pointing beyond EOF fails when SQLite reads rows,
            # not during open. This exercises the statement's corruption hook.
            database.execSQL("PRAGMA writable_schema = ON")
            database.execSQL("UPDATE sqlite_master SET rootpage = 999999 WHERE name = 'records'")
            database.execSQL("PRAGMA writable_schema = OFF")
            database.execSQL("PRAGMA schema_version = 2")
            size = file.length()
            statement = database.compileStatement("SELECT value FROM records")
            try:
                failed = False
                try:
                    statement.simpleQueryForString()
                except SQLiteDatabaseCorruptException:
                    failed = True
                assert failed and handler.calls == 1
                assert handler.path == file.getPath()
                assert file.exists() and file.length() == size
            finally:
                statement.close()
        finally:
            database.close()
    finally:
        assert file.delete()


def test_scalar_query_reads_values_larger_than_a_cursor_window() -> None:
    database = open_database(":memory:")
    try:
        database.execSQL("CREATE TABLE records (key TEXT PRIMARY KEY, value TEXT)")
        value = "雪" * 900_000 + "\x00end"
        statement = database.compileStatement("INSERT INTO records VALUES (?, ?)")
        try:
            statement.bindString(i32(1), "large")
            statement.bindString(i32(2), value)
            statement.executeInsert()
        finally:
            statement.close()
        statement = database.compileStatement("SELECT value FROM records WHERE key = ?")
        try:
            statement.bindString(i32(1), "large")
            assert statement.simpleQueryForString() == value
            statement.bindString(i32(1), "missing")
            missing = False
            try:
                statement.simpleQueryForString()
            except SQLiteDoneException:
                missing = True
            assert missing
            database.execSQL("INSERT INTO records VALUES ('null', NULL)")
            statement.bindString(i32(1), "null")
            assert statement.simpleQueryForString() is None
        finally:
            statement.close()
    finally:
        database.close()


def test_bound_unicode_values_nulls_and_64_bit_numbers_survive_reopen() -> None:
    file = create_temp_file("sqlite-contract", ".db", application_context().getFilesDir())
    try:
        database = open_database(file.getPath())
        try:
            database.execSQL("CREATE TABLE records (key TEXT PRIMARY KEY, value TEXT, version INTEGER)")
            statement = database.compileStatement("INSERT INTO records VALUES (?, ?, ?)")
            try:
                statement.bindString(i32(1), "quote' key")
                statement.bindString(i32(2), "😀雪\n\r\t\x00end")
                statement.bindLong(i32(3), 9007199254740993)
                assert statement.executeInsert() > 0
                statement.clearBindings()
                statement.bindString(i32(1), "null")
                statement.bindNull(i32(2))
                statement.bindLong(i32(3), -9223372036854775808)
                statement.executeInsert()
            finally:
                statement.close()
            database.setVersion(i32(1))
        finally:
            database.close()
        reopened = open_database(file.getPath())
        try:
            assert reopened.getVersion() == 1
            args = JVMArray[str](1)
            args[0] = "quote' key"
            cursor = reopened.rawQuery("SELECT value, version FROM records WHERE key = ?", args)
            try:
                assert cursor.moveToNext()
                assert cursor.getString(i32(0)) == "😀雪\n\r\t\x00end"
                assert cursor.getLong(i32(1)) == 9007199254740993
                assert not cursor.moveToNext()
            finally:
                cursor.close()
            cursor = reopened.rawQuery("SELECT value, version FROM records WHERE key = 'null'", None)
            try:
                assert cursor.moveToNext()
                assert cursor.isNull(i32(0))
                assert cursor.getString(i32(0)) is None
                assert cursor.getLong(i32(1)) == -9223372036854775808
            finally:
                cursor.close()
        finally:
            reopened.close()
    finally:
        assert file.delete()


def test_failed_transaction_rolls_back_and_later_transaction_commits() -> None:
    database = open_database(":memory:")
    try:
        database.execSQL("CREATE TABLE records (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        failed = False
        database.beginTransaction()
        try:
            database.execSQL("INSERT INTO records VALUES ('one', 'first')")
            database.execSQL("INSERT INTO records VALUES ('one', 'duplicate')")
            database.setTransactionSuccessful()
        except SQLiteConstraintException:
            failed = True
        finally:
            database.endTransaction()
        assert failed and not database.inTransaction()
        cursor = database.rawQuery("SELECT count(*) FROM records", None)
        try:
            assert cursor.moveToNext() and cursor.getLong(i32(0)) == 0
        finally:
            cursor.close()
        database.beginTransaction()
        try:
            database.execSQL("INSERT INTO records VALUES ('one', 'committed')")
            database.setTransactionSuccessful()
        finally:
            database.endTransaction()
        statement = database.compileStatement("DELETE FROM records WHERE key = ?")
        try:
            statement.bindString(i32(1), "one")
            assert statement.executeUpdateDelete() == 1
            assert statement.executeUpdateDelete() == 0
        finally:
            statement.close()
    finally:
        database.close()
