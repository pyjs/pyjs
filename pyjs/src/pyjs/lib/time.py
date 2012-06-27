# Check http://docs.python.org/library/time.html

from __pyjamas__ import JS, debugger
import math

timezone = JS("60 * (new Date(new Date()['getFullYear'](), 0, 1))['getTimezoneOffset']()")
altzone = JS("60 * (new Date(new Date()['getFullYear'](), 6, 1))['getTimezoneOffset']()")
if altzone > timezone:
    # Probably on southern parth of the earth...
    d = timezone
    timezone = altzone
    altzone = d
_dst = timezone - altzone
d = JS("(new Date(new Date()['getFullYear'](), 0, 1))")
d = str(d.toLocaleString()).split()[-1]
if d[0] == '(':
    d = d[1:-1]
tzname = (d, None)
del d

__c__days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
__c__months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def time():
    return float(JS("new Date()['getTime']() / 1000.0"))

class struct_time(object):
    n_fields = 9
    n_sequence_fields = 9
    n_unnamed_fields = 0
    tm_year = None
    tm_mon = None
    tm_mday = None
    tm_hour = None
    tm_min = None
    tm_sec = None
    tm_wday = None
    tm_yday = None
    tm_isdst = None

    def __init__(self, ttuple=None):
        if not ttuple is None:
            self.tm_year = ttuple[0]
            self.tm_mon = ttuple[1]
            self.tm_mday = ttuple[2]
            self.tm_hour = ttuple[3]
            self.tm_min = ttuple[4]
            self.tm_sec = ttuple[5]
            self.tm_wday = ttuple[6]
            self.tm_yday = ttuple[7]
            self.tm_isdst = ttuple[8]

    def __str__(self):
        t = (
            self.tm_year,
            self.tm_mon,
            self.tm_mday,
            self.tm_hour,
            self.tm_min,
            self.tm_sec,
            self.tm_wday,
            self.tm_yday,
            self.tm_isdst,
        )
        return t.__str__()

    def __repr__(self):
        return self.__str__()

    def __getitem__(self, idx):
        return [self.tm_year, self.tm_mon, self.tm_mday,
                self.tm_hour, self.tm_min, self.tm_sec,
                self.tm_wday, self.tm_yday, self.tm_isdst][idx]

    def __getslice__(self, lower, upper):
        return [self.tm_year, self.tm_mon, self.tm_mday,
                self.tm_hour, self.tm_min, self.tm_sec,
                self.tm_wday, self.tm_yday, self.tm_isdst][lower:upper]

def gmtime(t=None):
    if t is None:
        t = time()
    date = JS("new Date(@{{t}}*1000)")
    tm = struct_time()
    tm_year = tm.tm_year = int(date.getUTCFullYear())
    tm.tm_mon = int(date.getUTCMonth()) + 1
    tm.tm_mday = int(date.getUTCDate())
    tm.tm_hour = int(date.getUTCHours())
    tm.tm_min = int(date.getUTCMinutes())
    tm.tm_sec = int(date.getUTCSeconds())
    tm.tm_wday = (int(date.getUTCDay()) + 6) % 7
    tm.tm_isdst = 0
    startOfYear = JS("new Date('Jan 1 '+ @{{tm_year}} +' GMT+0000')")
    tm.tm_yday = 1 + int((t - startOfYear.getTime()/1000)/86400)
    return tm

def localtime(t=None):
    if t is None:
        t = time()
    date = JS("new Date(@{{t}}*1000)")
    dateOffset = date.getTimezoneOffset()
    tm = struct_time()
    tm_year = tm.tm_year = int(date.getFullYear())
    tm_mon = tm.tm_mon = int(date.getMonth()) + 1
    tm_mday = tm.tm_mday = int(date.getDate())
    tm.tm_hour = int(date.getHours())
    tm.tm_min = int(date.getMinutes())
    tm.tm_sec = int(date.getSeconds())
    tm.tm_wday = (int(date.getDay()) + 6) % 7
    tm.tm_isdst = 0 if timezone == 60*date.getTimezoneOffset() else 1
    startOfYear = JS("new Date(@{{tm_year}},0,1)") # local time
    startOfYearOffset = startOfYear.getTimezoneOffset()
    startOfDay = JS("new Date(@{{tm_year}},@{{tm_mon}}-1,@{{tm_mday}})")
    dt = float(startOfDay.getTime() - startOfYear.getTime())/1000
    dt = dt + 60 * (startOfYearOffset - dateOffset)
    tm.tm_yday = 1 + int(dt/86400.0)
    return tm

def mktime(t):
    """mktime(tuple) -> floating point number
    Convert a time tuple in local time to seconds since the Epoch."""
    tm_year = t[0]
    tm_mon = t[1] - 1
    tm_mday = t[2]
    tm_hour = t[3]
    tm_min = t[4]
    tm_sec = t[5]
    date = JS("new Date(@{{tm_year}}, @{{tm_mon}}, @{{tm_mday}}, @{{tm_hour}}, @{{tm_min}}, @{{tm_sec}})") # local time
    utc = JS("Date['UTC'](@{{tm_year}}, @{{tm_mon}}, @{{tm_mday}}, @{{tm_hour}}, @{{tm_min}}, @{{tm_sec}})")/1000
    ts = date.getTime() / 1000
    if t[8] == 0:
        if ts - utc == timezone:
            return ts
        return ts + _dst
    return ts

def strftime(fmt, t=None):
    if t is None:
        t = localtime()
    else:
        if not isinstance(t, struct_time) and len(t) != 9:
            raise TypeError('argument must be 9-item sequence, not float')
    tm_year = t[0]
    tm_mon = t[1]
    tm_mday = t[2]
    tm_hour = t[3]
    tm_min = t[4]
    tm_sec = t[5]
    tm_wday = t[6]
    tm_yday = t[7]
    date = JS("new Date(@{{tm_year}}, @{{tm_mon}} - 1, @{{tm_mday}}, @{{tm_hour}}, @{{tm_min}}, @{{tm_sec}})")
    startOfYear = JS("new Date(@{{tm_year}},0,1)")
    firstMonday = 1 - ((startOfYear.getDay() + 6) % 7) + 7
    firstWeek = JS("new Date(@{{tm_year}},0,@{{firstMonday}})")
    weekNo = date.getTime() - firstWeek.getTime()
    if weekNo < 0:
        weekNo = 0
    else:
        weekNo = 1 + int(weekNo/604800000)

    def format(c):
        if c == '%':
            return '%'
        elif c == 'a':
            return format('A')[:3]
        elif c == 'A':
            return __c__days[format('w')]
        elif c == 'b':
            return format('B')[:3]
        elif c == 'B':
            return __c__months[tm_mon-1]
        elif c == 'c':
            return date.toLocaleString()
        elif c == 'd':
            return "%02d" % tm_mday
        elif c == 'H':
            return "%02d" % tm_hour
        elif c == 'I':
            return "%02d" % (tm_hour % 12)
        elif c == 'j':
            return "%03d" % tm_yday
        elif c == 'm':
            return "%02d" % tm_mon
        elif c == 'M':
            return "%02d" % tm_min
        elif c == 'p': # FIXME: should be locale dependent
            if tm_hour < 12:
                return "AM"
            return "PM"
        elif c == 'S':
            return "%02d" % tm_sec
        elif c == 'U':
            raise NotImplementedError("strftime format character '%s'" % c)
        elif c == 'w':
            return "%d" % ((tm_wday+1) % 7)
        elif c == 'W':
            return "%d" % weekNo
        elif c == 'x':
            return "%s" % date.toLocaleDateString()
        elif c == 'X':
            return "%s" % date.toLocaleTimeString()
        elif c == 'y':
            return "%02d" % (tm_year % 100)
        elif c == 'Y':
            return "%04d" % tm_year
        elif c == 'Z':
            raise NotImplementedError("strftime format character '%s'" % c)
        return "%" + c
    result = ''
    remainder = fmt
    re_pct = JS("/([^%]*)%(.)(.*)/")
    JS("var a, fmtChar;")
    while remainder:
        JS("""
        @{{!a}} = @{{re_pct}}['exec'](@{{remainder}});
        if (!@{{!a}}) {
            @{{result}} += @{{remainder}};
            @{{remainder}} = false;
        } else {
            @{{result}} += @{{!a}}[1];
            @{{!fmtChar}} = @{{!a}}[2];
            @{{remainder}} = @{{!a}}[3];
            if (typeof @{{!fmtChar}} != 'undefined') {
                @{{result}} += @{{format}}(@{{!fmtChar}});
            }
        }
        """)
    return str(result)

def asctime(t=None):
    if t is None:
        t = localtime()
    return "%s %s %02d %02d:%02d:%02d %04d" % (__c__days[(t[6]+1)%7][:3], __c__months[t[1]-1], t[2], t[3], t[4], t[5], t[0])

def ctime(t=None):
    return asctime(localtime(t))

# This is an incomplete implementation and comes from
# Adrien Di Mascio
# See http://www.logilab.org/blogentry/6731
JS("""
var _DATE_FORMAT_REGXES = {
    'Y': new RegExp('^-?[0-9]{4}'),
    'y': new RegExp('^-?[0-9]{2}'),
    'd': new RegExp('^[0-9]{2}'),
    'm': new RegExp('^[0-9]{2}'),
    'H': new RegExp('^[0-9]{2}'),
    'M': new RegExp('^[0-9]{2}'),
    'S': new RegExp('^[0-9]{2}')
}

/*
 * _parseData does the actual parsing job needed by `strptime`
 */
function _parseDate(datestring, format) {
    var parsed = {};
    for (var i1=0,i2=0;i1<format['length'];i1++,i2++) {
        var c1 = format[i1];
        var c2 = datestring[i2];
        if (c1 == '%') {
            c1 = format[++i1];
            var data = _DATE_FORMAT_REGXES[c1]['exec'](datestring['substring'](i2));
            if (!data['length']) {
                return null;
            }
            data = data[0];
            i2 += data['length']-1;
            var value = parseInt(data, 10);
            if (isNaN(value)) {
                return null;
            }
            parsed[c1] = value;
            continue;
        }
        if (c1 != c2) {
            return null;
        }
    }
    return parsed;
}

/*
 * basic implementation of strptime. The only recognized formats
 * defined in _DATE_FORMAT_REGEXES (i['e']. %Y, %d, %m, %H, %M)
 */
function strptime(datestring, format) {
    var parsed = _parseDate(datestring, format);
    if (!parsed) {
        return null;
    }
    // create initial date (!!! year=0 means 1900 !!!)
    var date = new Date(0, 0, 1, 0, 0);
    date['setFullYear'](0); // reset to year 0
    if (typeof parsed['Y'] != "undefined") {
        date['setFullYear'](parsed['Y']);
    }
    if (typeof parsed['y'] != "undefined") {
        date['setFullYear'](2000+parsed['y']);
    }
    if (typeof parsed['m'] != "undefined") {
        if (parsed['m'] < 1 || parsed['m'] > 12) {
            return null;
        }
        // !!! month indexes start at 0 in javascript !!!
        date['setMonth'](parsed['m'] - 1);
    }
    if (typeof parsed['d'] != "undefined") {
        if (parsed['m'] < 1 || parsed['m'] > 31) {
            return null;
        }
        date['setDate'](parsed['d']);
    }
    if (typeof parsed['H'] != "undefined") {
        if (parsed['H'] < 0 || parsed['H'] > 23) {
            return null;
        }
        date['setHours'](parsed['H']);
    }
    if (typeof parsed['M'] != "undefined") {
        if (parsed['M'] < 0 || parsed['M'] > 59) {
            return null;
        }
        date['setMinutes'](parsed['M']);
    }
    if (typeof parsed['S'] != "undefined") {
        if (parsed['S'] < 0 || parsed['S'] > 59) {
            return null;
        }
        date['setSeconds'](parsed['S']);
    }
    // new Date()['setFullYear'](2010,01,31) returns March 3
    if (typeof parsed['m'] != "undefined" && date['getMonth']() != parsed['m']-1) {
        // date['getMonth']() and parsed['m'] don't correspond
        return null;
    }
    return date;
};
""")

# For use in datetime.datetime.strptime()
# There's a timestamp required
def _strptime(datestring, format):
    try:
        return float(JS("strptime(@{{datestring}}['valueOf'](), @{{format}}['valueOf']())['getTime']() / 1000.0"))
    except:
        raise ValueError("Invalid or unsupported values for strptime: '%s', '%s'" % (datestring, format))

def strptime(datestring, format):
    try:
        tt = localtime(float(JS("strptime(@{{datestring}}['valueOf'](), @{{format}}['valueOf']())['getTime']() / 1000.0")))
        tt.tm_isdst = -1
        return tt
    except:
        raise ValueError("Invalid or unsupported values for strptime: '%s', '%s'" % (datestring, format))
