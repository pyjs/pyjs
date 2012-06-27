from __pyjamas__ import JS

def ceil(x): return float(JS("Math['ceil'](@{{x}}['valueOf']())"))
def fabs(x): return float(JS("Math['abs'](@{{x}}['valueOf']())"))
def floor(x): return float(JS("Math['floor'](@{{x}}['valueOf']())"))
def exp(x): return float(JS("Math['exp'](@{{x}}['valueOf']())"))
def log(x, base=None):
    if base is None:
        return float(JS("Math['log'](@{{x}}['valueOf']())"))
    return float(JS("Math['log'](@{{x}}['valueOf']()) / Math['log'](@{{base}}['valueOf']())"))
def pow(x, y): return float(JS("Math['pow'](@{{x}}['valueOf'](), @{{y}}['valueOf']())"))
def sqrt(x): return float(JS("Math['sqrt'](@{{x}}['valueOf']())"))
def cos(x): return float(JS("Math['cos'](@{{x}}['valueOf']())"))
def sin(x): return float(JS("Math['sin'](@{{x}}['valueOf']())"))
def tan(x): return float(JS("Math['tan'](@{{x}}['valueOf']())"))
def acos(x): return float(JS("Math['acos'](@{{x}}['valueOf']())"))
def asin(x): return float(JS("Math['asin'](@{{x}}['valueOf']())"))
def atan(x): return float(JS("Math['atan'](@{{x}}['valueOf']())"))
def atan2(x, y): return float(JS("Math['atan2'](@{{x}}['valueOf'](), @{{y}}['valueOf']())"))

pi = float(JS("Math['PI']"))
e = float(JS("Math['E']"))
__log10__ = float(JS("Math['LN10']"))
__log2__ = log(2)

# This is not the real thing, but i helps to start with the small numbers
def fsum(x):
    xx = [(fabs(v), i) for i, v in enumerate(x)]
    xx.sort()
    sum = 0
    for i in xx:
        sum += x[i[1]]
    return sum

def frexp(x):
    global __log2__
    if x == 0:
        return (0.0, 0)
    # x = m * 2**e
    e = int(log(abs(x))/__log2__) + 1
    m = x / (2.**e)
    return (m,e)

def ldexp(x, i):
    return x * (2**i)

def log10 (arg):
    return log(arg) / __log10__

def degrees(x):
    return x * 180 / pi

def radians(x):
    return x * pi / 180

def hypot(x, y):
    """Calculate the hypotenuse the safe way, avoiding over- and underflows"""
    x = abs(x)
    y = abs(y)
    x, y = max(x, y), min(x, y)
    return x * sqrt(1 + (y/x) * (y/x))

