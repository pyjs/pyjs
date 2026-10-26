"""The same native SQLite contract runs under Robolectric and on a device."""
import pytest

from pyjs.android.sqlite import (
    SQLiteConstraintException,
    SQLiteDoneException,
    open_database,
)
from pyjs.android.testing import application_context
from pyjs.java import JVMArray, i32
from pyjs.java.io import create_temp_file

pytestmark = pytest.mark.pyjs_android_jvm


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
