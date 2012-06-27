from __pyjamas__ import JS

from time import __c__days, __c__months, strftime, localtime, gmtime, _strptime

MINYEAR = 1
MAXYEAR = 1000000

# __Jan_01_0001 : local time for Mon Jan 01 0001 00:00:00
__Jan_01_0001 = JS("""(new Date((new Date('Jan 1 1971'))['getTime']() - 62167132800000))['getTime']()""")


class date:
    def __init__(self, year, month, day, d=None):
        if d is None:
            d = JS("""new Date(@{{year}}, @{{month}} - 1, @{{day}}, 0, 0, 0, 0)""")
        self._d = d
        self.year = d.getFullYear()
        self.month = d.getMonth() + 1.0
        self.day = d.getDate()

    @classmethod
    def today(self):
        return date(d=JS("""new Date()"""))

    @classmethod
    def fromtimestamp(self, timestamp):
        d = JS("""new Date()""")
        d.setTime(timestamp * 1000.0)
        return date(0, 0, 0, d=d)

    @classmethod
    def fromordinal(self, ordinal):
        t = __Jan_01_0001 + (ordinal-1) * 86400000.0
        d = JS("""new Date(@{{t}})""")
        return date(0, 0, 0, d=d)

    def ctime(self):
        return "%s %s %2d %02d:%02d:%02d %04d" % (__c__days[self._d.getDay()][:3], __c__months[self._d.getMonth()][:3], self._d.getDate(), self._d.getHours(), self._d.getMinutes(), self._d.getSeconds(), self._d.getFullYear())

    def isocalendar(self):
        isoyear = isoweeknr = isoweekday = None
        _d = self._d
        JS("""
            var gregdaynumber = function(year, month, day) {
                var y = year;
                var m = month;
                if (month < 3) {
                    y--;
                    m += 12;
                }
                return Math['floor'](365.25 * y) - Math['floor'](y / 100) + Math['floor'](y / 400) + Math['floor'](30.6 * (m + 1)) + day - 62;
            };

            var year = @{{_d}}['getFullYear']();
            var month = @{{_d}}['getMonth']();
            var day = @{{_d}}['getDate']();
            var wday = @{{_d}}['getDay']();

            @{{isoweekday}} = ((wday + 6) % 7) + 1;
            @{{isoyear}} = year;

            var d0 = gregdaynumber(year, 1, 0);
            var weekday0 = ((d0 + 4) % 7) + 1;

            var d = gregdaynumber(year, month + 1, day);
            @{{isoweeknr}} = Math['floor']((d - d0 + weekday0 + 6) / 7) - Math['floor']((weekday0 + 3) / 7);

            if ((month == 11) && ((day - @{{isoweekday}}) > 27)) {
                @{{isoweeknr}} = 1;
                @{{isoyear}} = @{{isoyear}} + 1;
            }

            if ((month == 0) && ((@{{isoweekday}} - day) > 3)) {
                d0 = gregdaynumber(year - 1, 1, 0);
                weekday0 = ((d0 + 4) % 7) + 1;
                @{{isoweeknr}} = Math['floor']((d - d0 + weekday0 + 6) / 7) - Math['floor']((weekday0 + 3) / 7);
                @{{isoyear}}--;
            }
        """)
        return (isoyear, isoweeknr, isoweekday)

    def isoformat(self):
        return "%04d-%02d-%02d" % (self.year, self.month, self.day)

    def isoweekday(self):
        return ((self._d.getDay() + 6) % 7) + 1

    def replace(self, year=None, month=None, day=None):
        if year is None:
            year = self.year
        if month is None:
            month = self.month
        if day is None:
            day = self.day
        return date(year, month, day)

    def strftime(self, format):
        return strftime(format, self.timetuple())

    def timetuple(self):
        tm = localtime(int(self._d.getTime() / 1000.0))
        tm.tm_hour = tm.tm_min = tm.tm_sec = 0
        return tm

    def toordinal(self):
        return 1 + int((self._d.getTime() - __Jan_01_0001) / 86400000.0)

    def weekday(self):
        return (self._d.getDay() + 6) % 7

    def __str__(self):
        return self.isoformat()

    def __cmp__(self, other):
        if isinstance(other, date) or isinstance(other, datetime):
            a = self._d.getTime()
            b = other._d.getTime()
            if a < b:
                return -1
            elif a == b:
                return 0
        else:
            raise TypeError("expected date or datetime object")
        return 1

    def __add__(self, other):
        if isinstance(other, timedelta):
            return date(self.year, self.month, self.day + other.days)
        else:
            raise TypeError("expected timedelta object")

    def __sub__(self, other):
        if isinstance(other, date) or isinstance(other, datetime):
            diff = self._d.getTime() - other._d.getTime()
            return timedelta(int(diff / 86400000.0), int(diff / 1000.0) % 86400, milliseconds=(diff % 86400000))
        elif isinstance(other, timedelta):
            return date(self.year, self.month, self.day - other.days)
        else:
            raise TypeError("expected date or datetime object")


class time:
    def __init__(self, hour, minute=0, second=0, microsecond=0, tzinfo=None, d=None):
        if tzinfo != None:
            raise NotImplementedError("tzinfo")
        if d is None:
            d = JS("""new Date(1970, 1, 1, @{{hour}}, @{{minute}}, @{{second}}, 0.5 + @{{microsecond}} / 1000.0)""")
        self._d = d
        self.hour = d.getHours()
        self.minute = d.getMinutes()
        self.second = d.getSeconds()
        self.microsecond = d.getMilliseconds() * 1000.0
        self.tzinfo = None

    def dst(self):
        raise NotImplementedError("dst")

    def isoformat(self):
        t = "%02d:%02d:%02d" % (self.hour, self.minute, self.second)
        if self.microsecond:
            t += ".%06d" % self.microsecond
        return t

    def replace(self, hour=None, minute=None, second=None, microsecond=None, tzinfo=None):
        if tzinfo != None:
            raise NotImplementedError("tzinfo")
        if hour is None:
            hour = self.hour
        if minute is None:
            minute = self.minute
        if second is None:
            second = self.second
        if microsecond is None:
            microsecond = self.microsecond
        return time(hour, minute, second, microsecond)

    def strftime(self, format):
        return strftime(format, localtime(int(self._d.getTime() / 1000.0)))

    def tzname(self):
        return None

    def utcoffset(self):
        return None

    def __str__(self):
        return self.isoformat()


class datetime(date, time):
    def __init__(self, year, month, day, hour=0, minute=0, second=0, microsecond=0, tzinfo=None, d=None):
        if d is None:
            d = JS("""new Date(@{{year}}, @{{month}} - 1, @{{day}}, @{{hour}}, @{{minute}}, @{{second}}, 0.5 + @{{microsecond}} / 1000.0)""")
        date.__init__(self, 0, 0, 0, d=d)
        time.__init__(self, 0, d=d)

    @classmethod
    def combine(self, date, time):
        return datetime(date.year, date.month, date.day, time.hour, time.minute, time.second, time.microsecond)

    @classmethod
    def fromtimestamp(self, timestamp, tz=None):
        if tz != None:
            raise NotImplementedError("tz")
        d = JS("""new Date()""")
        d.setTime(timestamp * 1000.0)
        return datetime(0, 0, 0, d=d)

    @classmethod
    def fromordinal(self, ordinal):
        d = JS("""new Date()""")
        d.setTime((ordinal - 719163.0) * 86400000.0)
        return datetime(0, 0, 0, d=d)

    @classmethod
    def now(self, tz=None):
        if tz != None:
            raise NotImplementedError("tz")
        return datetime(0, 0, 0, d=JS("""new Date()"""))

    @classmethod
    def strptime(self, datestring, format):
        return self.fromtimestamp(_strptime(datestring, format))

    @classmethod
    def utcfromtimestamp(self, timestamp):
        tm = gmtime(timestamp)
        return datetime(tm.tm_year, tm.tm_mon, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec)

    @classmethod
    def utcnow(self):
        d = JS("""new Date()""")
        return datetime.utcfromtimestamp(int(d.getTime() / 1000.0))

    def timetuple(self):
        return localtime(int(self._d.getTime() / 1000.0))

    def astimezone(self, tz):
        raise NotImplementedError("astimezone")

    def date(self):
        return date(self.year, self.month, self.day)

    def time(self):
        return time(self.hour, self.minute, self.second, self.microsecond)

    def replace(self, year=None, month=None, day=None, hour=None, minute=None, second=None, microsecond=None, tzinfo=None):
        if tzinfo != None:
            raise NotImplementedError("tzinfo")
        if year is None:
            year = self.year
        if month is None:
            month = self.month
        if day is None:
            day = self.day
        if hour is None:
            hour = self.hour
        if minute is None:
            minute = self.minute
        if second is None:
            second = self.second
        if microsecond is None:
            microsecond = self.microsecond
        return datetime(year, month, day, hour, minute, second, microsecond)

    def timetz(self):
        raise NotImplementedError("timetz")

    def utctimetuple(self):
        return gmtime(self._d.getTime() / 1000.0)

    def isoformat(self, sep='T'):
        t = "%04d-%02d-%02d%s%02d:%02d:%02d" % (self.year, self.month, self.day, sep, self.hour, self.minute, self.second)
        if self.microsecond:
            t += ".%06d" % self.microsecond
        return t

    def __add__(self, other):
        if isinstance(other, timedelta):
            year = self.year
            month = self.month
            day = self.day + other.days
            hour = self.hour + (other.seconds / 3600.0)
            minute = self.minute + ((other.seconds / 60.0) % 60)
            second = self.second + (other.seconds % 60)
            microsecond = self.microsecond + other.microseconds
            d = JS("""new Date(@{{year}}, @{{month}}, @{{day}}, @{{hour}}, @{{minute}}, @{{second}}, @{{microsecond}})""")
            return datetime(d=d)
        else:
            raise TypeError("expected timedelta object")

    def __sub__(self, other):
        if isinstance(other, date) or isinstance(other, datetime):
            diff = self._d.getTime() - other._d.getTime()
            return timedelta(int(diff / 86400000.0), int(diff / 1000.0) % 86400, milliseconds=(diff % 86400000))
        elif isinstance(other, timedelta):
            year = self.year
            month = self.month
            day = self.day - other.days
            hour = self.hour - (other.seconds / 3600.0)
            minute = self.minute - ((other.seconds / 60.0) % 60)
            second = self.second - (other.seconds % 60)
            microsecond = self.microsecond - other.microseconds

            d = JS("""new Date(@{{year}}, @{{month}}, @{{day}}, @{{hour}}, @{{minute}}, @{{second}}, @{{microsecond}})""")
            return datetime(d=d)
        else:
            raise TypeError("expected date or datetime object")

    def __str__(self):
        return self.isoformat(' ')


class timedelta:
    def __init__(self, days=0, seconds=0, microseconds=0, milliseconds=0, minutes=0, hours=0, weeks=0):
        self.days = (weeks * 7.0) + days
        self.seconds = (hours * 3600.0) + (minutes * 60.0) + seconds
        self.microseconds = (milliseconds * 1000.0) + microseconds

class tzinfo(object):
    pass

date.min = date(1,1,1)
date.max = date(9999,12,31)
date.resolution = timedelta(1)

time.min = time(0,0)
time.max = time(23,59,59,999999)
time.resolution = timedelta(0,0,1)

datetime.min = datetime(1,1,1,0,0)
datetime.max = datetime(9999,12,31,23,59,59,999999)
datetime.resolution = timedelta(0,0,1)

timedelta.min = timedelta(-999999999)
timedelta.max = timedelta(999999999, hours=23, minutes=59, seconds=59, microseconds=999999)
timedelta.resolution = timedelta(0,0,1)
