"""
* Copyright 2007,2008,2009 John C. Gunther
* Copyright (C) 2009 Luke Kenneth Casson Leighton <lkcl@lkcl.net>
*
* Licensed under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License. You may obtain a copy of the License at:
*
*  http:#www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
* either express or implied. See the License for the specific
* language governing permissions and limitations under the
* License.
*
"""



from pyjamas.chart import AnnotationLocation
from pyjamas.chart.HovertextChunk import formatAsHovertext

import pygwt

# axis types (used to define which y-axis each curve is on)
class YAxisId(object):
    pass


"""* Default size, in pixels, of text used to annotate individual
** plotted points on a curve.
**
** @see Curve.Point#setFontSize Point.setFontSize
"""
DEFAULT_ANNOTATION_FONTSIZE = 12

"""*
* Default pixel height of rectangular "brush" that defines
* how close the mouse cursor must be to a rendered symbol for
* it to be "touched" (which pops up its hover feedback).
*
* @see Symbol#setBrushHeight setBrushHeight
* @see Symbol#setBrushWidth setBrushWidth
* @see #DEFAULT_BRUSH_WIDTH DEFAULT_BRUSH_WIDTH
"""
DEFAULT_BRUSH_HEIGHT = 1
"""*
*
* Default pixel width of rectangular "brush" that defines how
* close the mouse cursor must be to a rendered symbol for it
* to be "touched" (which pops up its hover feedback).
*
* @see Symbol#setBrushHeight setBrushHeight
* @see Symbol#setBrushWidth setBrushWidth
* @see #DEFAULT_BRUSH_HEIGHT DEFAULT_BRUSH_HEIGHT
"""
DEFAULT_BRUSH_WIDTH = 1

"""* Default color of border around the chart legend
**
** @see #setLegendBorderColor setLegendBorderColor
**
*"""
DEFAULT_LEGEND_BORDER_COLOR = "black"
"""* Default width of border around the chart legend
**
** @see #setLegendBorderWidth setLegendBorderWidth
**
*"""
DEFAULT_LEGEND_BORDER_WIDTH = 1
"""* Default style of border around the chart legend
**
** @see #setLegendBorderStyle setLegendBorderStyle
**
*"""
DEFAULT_LEGEND_BORDER_STYLE = "solid"

"""* Default color of background of the chart legend
**
** @see #setLegendBackgroundColor setLegendBackgroundColor
**
"""
DEFAULT_LEGEND_BACKGROUND_COLOR = "transparent"
"""*
** The default color of any text appearing in a chart's
** legend, annotations, or tick labels.
**
** @see #setLegendFontColor setLegendFontColor
** @see Axis#setTickLabelFontColor setTickLabelFontColor
** @see Curve.Point#setAnnotationFontColor setAnnotationFontColor
**
*"""
DEFAULT_FONT_COLOR ="black"
"""*
** Default style of axis label and legend fonts.
**
** @see #setLegendFontStyle setLegendFontStyle
** @see Axis#setTickLabelFontStyle setTickLabelFontStyle
** @see Curve.Point#setAnnotationFontStyle
** setAnnotationFontStyle
**
*"""
DEFAULT_FONT_STYLE = "normal"
"""* Default weight of axis label and legend fonts.
**
** @see #setLegendFontWeight setLegendFontWeight
** @see Axis#setTickLabelFontWeight setTickLabelFontWeight
** @see Curve.Point#setAnnotationFontWeight
** setAnnotationFontWeight
**
*"""

DEFAULT_FONT_WEIGHT = "normal"

"""*
** The default template string used to generate the hovertext
** displayed when the user hovers their mouse above a point
** on a curve (pie slices have a different default).
**
** @see Symbol#setHovertextTemplate setHovertextTemplate
** @see #DEFAULT_PIE_SLICE_HOVERTEXT_TEMPLATE
**    DEFAULT_PIE_SLICE_HOVERTEXT_TEMPLATE
**
"""
DEFAULT_HOVERTEXT_TEMPLATE = formatAsHovertext("(${x}, ${y})")
"""*
** The default hover feedback location used to position the
** hover feedback when the user hovers their mouse above a point
** on a curve (pie slices, and bar symbols have different
** defaults).
**
** @see Symbol#setHoverLocation setHoverLocation
** @see #DEFAULT_PIE_SLICE_HOVER_LOCATION DEFAULT_PIE_SLICE_HOVER_LOCATION
** @see #DEFAULT_VBAR_BASELINE_HOVER_LOCATION DEFAULT_VBAR_BASELINE_HOVER_LOCATION
** @see #DEFAULT_VBARBOTTOM_HOVER_LOCATION DEFAULT_VBARBOTTOM_HOVER_LOCATION
** @see #DEFAULT_VBARTOP_HOVER_LOCATION DEFAULT_VBARTOP_HOVER_LOCATION
** @see #DEFAULT_HBAR_BASELINE_HOVER_LOCATION DEFAULT_HBAR_BASELINE_HOVER_LOCATION
** @see #DEFAULT_HBARLEFT_HOVER_LOCATION DEFAULT_HBARLEFT_HOVER_LOCATION
** @see #DEFAULT_HBARRIGHT_HOVER_LOCATION DEFAULT_HBARRIGHT_HOVER_LOCATION
**
"""
DEFAULT_HOVER_LOCATION = AnnotationLocation.NORTHWEST
"""* The default fontsize of text that appears
** in the chart's legend (key).
**
** @see Axis#setTickLabelFontSize setTickLabelFontSize
** @see #getXAxis getXAxis
** @see #getYAxis getYAxis
** @see #getY2Axis getY2Axis
**
*"""
DEFAULT_LEGEND_FONTSIZE = 12


"""*
** The default background color used for the chart's plot area
** if none is specified.
**
** @see #setPlotAreaBackgroundColor setPlotAreaBackgroundColor
**
*"""
DEFAULT_PLOTAREA_BACKGROUND_COLOR = "transparent"
"""*
** The default border color used for the chart's plot area
** if none is specified.
**
** @see #setPlotAreaBorderColor setPlotAreaBorderColor
**
*"""
DEFAULT_PLOTAREA_BORDER_COLOR = "black"
"""*
** The default style of the border around the chart's plot area
** if none is specified.
**
** @see #setPlotAreaBorderStyle setPlotAreaBorderStyle
**
*"""
DEFAULT_PLOTAREA_BORDER_STYLE = "solid"
"""*
** The default width of the border around the chart's plot area
** if none is specified.
**
** @see #setPlotAreaBorderWidth setPlotAreaBorderWidth
**
*"""
DEFAULT_PLOTAREA_BORDER_WIDTH = 0
"""*
** The default CSS background color used for symbols if none is
** specified.
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setBackgroundColor setBackgroundColor
*"""
DEFAULT_SYMBOL_BACKGROUND_COLOR = "transparent"
"""*
** The default CSS border colors used for symbols if none are
** specified. These defaults are, in order of the curve's
** integer index: red, green, blue, fuchsia, aqua, teal,
** maroon, lime, navy, silver, olive, purple.  This sequence
** repeats if there are more than 12 curves.
** <p>
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setBorderColor setBorderColor
**
*"""

DEFAULT_SYMBOL_BORDER_COLORS = \
                ["red", "green", "blue",
                "fuchsia", "aqua", "teal",
                "maroon", "lime", "navy",
                "silver", "olive", "purple"]

"""*
** The default CSS border style used for symbols if none is
** specified; this default is "solid".
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setBorderStyle setBorderStyle
**
*"""
DEFAULT_SYMBOL_BORDER_STYLE = "solid"
"""*
** The default CSS border width used for symbols if none is
** specified; this default is 1 pixel.
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setBorderWidth setBorderWidth
**
*"""
DEFAULT_SYMBOL_BORDER_WIDTH = 1
"""*
** The default spacing between discrete, rectangular, elements
** used to simulate continuous graphical elements. This
** default does not apply to bar chart symbol types or
** the LINE symbol type, which have their own default
** fill spacings.
** <p>
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setFillSpacing setFillSpacing
** @see Symbol#setFillThickness setFillThickness
** @see #DEFAULT_BAR_FILL_SPACING
**      DEFAULT_BAR_FILL_SPACING
** @see #DEFAULT_LINE_FILL_SPACING
**      DEFAULT_LINE_FILL_SPACING
**
*"""
DEFAULT_SYMBOL_FILL_SPACING = 4
"""*
** The default "thickness" of the rectangular elements used to
** simulate continuous graphical objects, such as connecting
** lines in line charts. This default applies to all symbol
** types <tt>except</tt> for those representing pie slices,
** whose default is
** <tt>DEFAULT_PIE_SLICE_FILL_THICKNESS</tt>, and the LINE
** symbol type, whose default is DEFAULT_LINE_FILL_THICKNESS.
**
** <p> Since this default thickness is 0 px, this implies
** that, except for pie slices and lines, no such continuous fill
** elements are generated by default. For example, if you
** want to have dotted connecting lines drawn between individual
** data points represented using the <tt>BOX_CENTER</tt>
** symbol type, you must explicitly specify a positive fill
** thickness (for solid connecting lines, the LINE symbol
** is usually far more efficient than using a fill thickness
** of 1px with the BOX_CENTER symbol).
**
** @see #DEFAULT_PIE_SLICE_FILL_THICKNESS
**      DEFAULT_PIE_SLICE_FILL_THICKNESS
** @see #DEFAULT_LINE_FILL_THICKNESS
**      DEFAULT_LINE_FILL_THICKNESS
** @see Curve#getSymbol getSymbol
** @see Symbol#setFillSpacing setFillSpacing
** @see Symbol#setFillThickness setFillThickness
**
*"""
DEFAULT_SYMBOL_FILL_THICKNESS = 0


"""*
** The default spacing between discrete, rectangular, elements
** used to simulate continuous filling of polygonal regions
** formed by connecting corresponding ends of successive
** bars in a bar chart.
** <p>
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setFillSpacing setFillSpacing
** @see Symbol#setFillThickness setFillThickness
** @see #DEFAULT_SYMBOL_FILL_SPACING DEFAULT_SYMBOL_FILL_SPACING
**
*"""
DEFAULT_BAR_FILL_SPACING = 0

"""*
** The default thickness of connecting lines drawn on
** curves whose symbols have the LINE symbol type.
**
** @see #DEFAULT_SYMBOL_FILL_THICKNESS
**      DEFAULT_SYMBOL_FILL_THICKNESS
** @see Curve#getSymbol getSymbol
** @see Symbol#setFillSpacing setFillSpacing
** @see Symbol#setFillThickness setFillThickness
**
*"""
DEFAULT_LINE_FILL_THICKNESS = 1


"""*
** The default spacing between discrete, rectangular, elements
** used to simulate continuously connected lines between
** successive points on a curve that uses the
** <tt>LINE</tt> symbol type.
** <p>
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setFillSpacing setFillSpacing
** @see Symbol#setFillThickness setFillThickness
** @see #DEFAULT_SYMBOL_FILL_SPACING DEFAULT_SYMBOL_FILL_SPACING
**
*"""
DEFAULT_LINE_FILL_SPACING = 0

"""*
** The default "spacing" between corresponding edges of the
** rectangular elements used to simulate continuous fill of pie
** slices.  <p>
**
** @see #DEFAULT_SYMBOL_FILL_SPACING
**      DEFAULT_SYMBOL_FILL_SPACING
** @see #DEFAULT_PIE_SLICE_FILL_THICKNESS
**      DEFAULT_PIE_SLICE_FILL_THICKNESS
** @see Curve#getSymbol getSymbol
** @see Symbol#setFillSpacing setFillSpacing
** @see Symbol#setFillThickness setFillThickness
**
*"""
DEFAULT_PIE_SLICE_FILL_SPACING = 4
"""*
** The default "thickness" of the rectangular elements
** used to simulate continuous fill of pie slices. This
** thickness defines the height of horizontal pie slice
** shading bars, and the width of vertical shading bars.
** <p>
**
** @see #DEFAULT_SYMBOL_FILL_THICKNESS
**      DEFAULT_SYMBOL_FILL_THICKNESS
** @see #DEFAULT_LINE_FILL_THICKNESS
**      DEFAULT_LINE_FILL_THICKNESS
** @see Curve#getSymbol getSymbol
** @see Symbol#setFillSpacing setFillSpacing
** @see Symbol#setFillThickness setFillThickness
**
*"""
DEFAULT_PIE_SLICE_FILL_THICKNESS = 2

"""*
** The default hovertext template used by symbols when they have a
** symbol type of of the form PIE_SLICE_*.
**
** @see Symbol#setHovertextTemplate setHovertextTemplate
** @see SymbolType#PIE_SLICE_OPTIMAL_SHADING PIE_SLICE_OPTIMAL_SHADING
** @see #DEFAULT_HOVERTEXT_TEMPLATE DEFAULT_HOVERTEXT_TEMPLATE
**
*"""
DEFAULT_PIE_SLICE_HOVERTEXT_TEMPLATE = formatAsHovertext("${pieSliceSize}")

"""*
** The default hover feedback location used by symbols when they have a
** symbol type of of the form PIE_SLICE_*.
**
** @see Symbol#setHoverLocation setHoverLocation
** @see #DEFAULT_HOVER_LOCATION DEFAULT_HOVER_LOCATION
**
*"""
DEFAULT_PIE_SLICE_HOVER_LOCATION = AnnotationLocation.OUTSIDE_PIE_ARC
"""*
** The default height (including borders) used for
** symbols if none is specified; this default is
** the same as for <tt>DEFAULT_SYMBOL_WIDTH</tt>
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setHeight setHeight
** @see #DEFAULT_SYMBOL_WIDTH DEFAULT_SYMBOL_WIDTH
**
*"""
DEFAULT_SYMBOL_HEIGHT = 7

"""*
** The default width (including borders) used for
** symbols if none is specified.
**
** @see Curve#getSymbol getSymbol
** @see Symbol#setWidth setWidth
** @see #DEFAULT_SYMBOL_WIDTH DEFAULT_SYMBOL_WIDTH
*"""
DEFAULT_SYMBOL_WIDTH = DEFAULT_SYMBOL_HEIGHT

"""*
* The default number of tick marks on each Axis.
*
* @see Axis#setTickCount setTickCount
*
"""
DEFAULT_TICK_COUNT = 10

"""* The default color (a CSS color specification) of tick labels
**
** @see Axis#setTickLabelFontColor setTickLabelFontColor
** @see #getXAxis getXAxis
** @see #getYAxis getYAxis
** @see #getY2Axis getY2Axis
*"""
DEFAULT_TICK_LABEL_FONT_COLOR ="black"

"""* The default CSS font-style applied to tick labels
**
** @see Axis#setTickLabelFontStyle setTickLabelFontStyle
** @see #getXAxis getXAxis
** @see #getYAxis getYAxis
** @see #getY2Axis getY2Axis
*"""
DEFAULT_TICK_LABEL_FONT_STYLE ="normal"

"""* The default CSS font-weight applied to tick labels
**
** @see Axis#setTickLabelFontWeight setTickLabelFontWeight
** @see #getXAxis getXAxis
** @see #getYAxis getYAxis
** @see #getY2Axis getY2Axis
*"""
DEFAULT_TICK_LABEL_FONT_WEIGHT ="normal"


"""* The default fontsize (in pixels) of tick labels
**
** @see Axis#setTickLabelFontSize setTickLabelFontSize
** @see #getXAxis getXAxis
** @see #getYAxis getYAxis
** @see #getY2Axis getY2Axis
*"""
DEFAULT_TICK_LABEL_FONTSIZE = 12
"""*
** The default GWT <tt>NumberFormat</tt> format string used to convert
** numbers to the text strings displayed as tick labels
** on X, Y, and Y2 axes.
**
** @see Axis#setTickLabelFormat setTickLabelFormat
** @see #getXAxis getXAxis
** @see #getYAxis getYAxis
** @see #getY2Axis getY2Axis
**
*"""
DEFAULT_TICK_LABEL_FORMAT = "#.##"

"""*
* The default length of tick marks, in pixels.
*
* @see Axis#setTickLength setTickLength
"""
DEFAULT_TICK_LENGTH = 6


"""*
* The default thickness of tick marks, in pixels.
*
* @see Axis#setTickThickness setTickThickness
"""
DEFAULT_TICK_THICKNESS = 1; # pixel

"""*
** The default location used to position the hover feedback
** when the user hovers their mouse above a point on a curve
** that uses a VBAR_BASELINE_* symbol type.
**
** @see Symbol#setHoverLocation setHoverLocation
** @see #DEFAULT_HOVER_LOCATION DEFAULT_HOVER_LOCATION
**
"""
DEFAULT_VBAR_BASELINE_HOVER_LOCATION = AnnotationLocation.FARTHEST_FROM_HORIZONTAL_BASELINE
"""*
** The default location used to position the hover feedback
** when the user hovers their mouse above a point on a curve
** that uses a VBAR_SOUTH* symbol type.
**
** @see Symbol#setHoverLocation setHoverLocation
** @see #DEFAULT_HOVER_LOCATION DEFAULT_HOVER_LOCATION
**
"""
DEFAULT_VBARBOTTOM_HOVER_LOCATION = AnnotationLocation.NORTH

"""*
** The default location used to position the hover feedback
** when the user hovers their mouse above a point on a curve
** that uses a VBAR_NORTH* symbol type.
**
** @see Symbol#setHoverLocation setHoverLocation
** @see #DEFAULT_HOVER_LOCATION DEFAULT_HOVER_LOCATION
**
"""
DEFAULT_VBARTOP_HOVER_LOCATION = AnnotationLocation.SOUTH

"""*
** The default location used to position the
** hover feedback when the user hovers their mouse above a point
** on a curve that uses a HBAR_BASELINE_* symbol type.
**
** @see Symbol#setHoverLocation setHoverLocation
** @see #DEFAULT_HOVER_LOCATION DEFAULT_HOVER_LOCATION
**
"""
DEFAULT_HBAR_BASELINE_HOVER_LOCATION = AnnotationLocation.FARTHEST_FROM_VERTICAL_BASELINE

"""*
** The default location used to position the
** hover feedback when the user hovers their mouse above a point
** on a curve that uses an HBAR_*WEST symbol type.
**
** @see Symbol#setHoverLocation setHoverLocation
** @see #DEFAULT_HOVER_LOCATION DEFAULT_HOVER_LOCATION
**
"""
DEFAULT_HBARLEFT_HOVER_LOCATION = AnnotationLocation.EAST

"""*
** The default location used to position the
** hover feedback when the user hovers their mouse above a point
** on a curve that uses an HBAR_*EAST symbol type.
**
** @see Symbol#setHoverLocation setHoverLocation
** @see #DEFAULT_HOVER_LOCATION DEFAULT_HOVER_LOCATION
**
"""
DEFAULT_HBARRIGHT_HOVER_LOCATION = AnnotationLocation.WEST

"""*
** The default upper bound on the width of widgets used
** in annotations and tick labels that GChart
** will assume for centering and similar alignment purposes.
**
** @see Curve.Point#setAnnotationWidget setAnnotationWidget
** @see Axis#addTick(double,Widget,int,int) addTick
**
*"""
DEFAULT_WIDGET_WIDTH_UPPERBOUND = 400
"""*
** The default upper bound on the height of widgets used
** in annotations and tick labels that GChart
** will assume for centering and similar alignment purposes.
**
** @see Curve.Point#setAnnotationWidget setAnnotationWidget
** @see Axis#addTick(double,Widget,int,int) addTick
**
*"""
DEFAULT_WIDGET_HEIGHT_UPPERBOUND = 400

"""*
*  The default width of the area of the chart in
*  which curves are displayed, in pixels.
"""
DEFAULT_X_CHARTSIZE = 300; # pixels
"""*
* The default height of the area of the chart in
* which curves are displayed, in pixels.
"""
DEFAULT_Y_CHARTSIZE = 300; # pixels

"""*
** In analogy to how it uses <tt>Double.NaN</tt> (Not a
** Number), GChart uses <tt>NAI</tt> (Not an Integer) to
** represent integers whose values have not been explicitly
** specified.
**
*"""
NAI = 2 ** 31

"""*
* Due to a well-known bug (see, for example, <a
* href="http:#www.hedgerwow.com/360/dhtml/css-ie-transparent-border.html">
* this explanation on Hedger Wang's blog</a>), though white
* may not be black in IE6, transparent borders certainly are.
* Besides this outright bug, different browsers define which
* element's background color "shines through" a transparent border
* differently. For example, in FF2, the background of the element
* containing the border shines through, which makes setting the
* border color to "transparent" equivalent to setting the border
* color to equal the background color. In IE7, the color of
* the chart's background "shines through"--which is more likely
* what you intended when you set a symbol's border to transparent.
* <p>
*
* To make it easy for you to eliminate such problems, and obtain a
* consistently behaving transparent-border behavior cross-browser,
* this special GChart-only "color" (recognized by all GChart border
* color related methods <i>except</i>
* <tt>GChart.setBorderColor</tt>) causes GChart to emulate a
* transparent border by eliminating the border entirely (setting
* it's width to 0) and changing the size and position of the element
* so as to make it look like the border is still "taking up space".
*
* <p>
*
*
* <blockquote><small> <i>Note:</i>The <tt>GChart.setBorderColor</tt>
* method, which sets the color of the border around the entire
* chart, does <i>not</i> support this keyword because GChart's
* transparent border emulation relies on changing the size of, and
* shifting the position of, the transparently bordered element. But,
* the position of the GChart as a whole is determined not by GChart,
* but by the enclosing page. Well-known CSS tricks, such as
* described in the "hedgerwow" link above, can be used if you need a
* Truely transparent border around the entire chart. Or, just fake
* it by setting the border color to equal the background color
* of the containing page.  </small></blockquote>
*
* <p>
*
* This differs from setting the border color to "transparent" (which
* you can still do should you need the "standard non-standard"
* transparent border color behavior) in subtle ways that can matter
* in special cases. For example, because the element is smaller than
* it is with "transparent", if you draw your symbols outside the
* chart rectangle, GChart will not be able to track the mouse moves
* inside the transparent region (yes, this is a fine point, but
* there could be other differences I'm not aware of). In almost
* every other case I can think of, though, setting the border color
* to this special keyword instead of "transparent" will be the
* simplest way to eliminate these inconsistent transparent border
* problems from your charts.
* <p>
*
* @see Symbol#setBorderColor setBorderColor
*
"""

TRANSPARENT_BORDER_COLOR = None

"""*
** A special value used to tell GChart that a property should
** be defined via CSS, not via an explicit Java API specification.
**
**
** Note that certain CSS convenience methods that could in
** principle have been added, such as those for defining the
** background image of a chart, were omitted because I
** thought they would almost never be used. Of course, you
** can always access these CSS properties "the old fashioned
** way" (via a CSS specification or methods of the GWT DOM class).
**
** <p>
** </small></blockquote>
**
** @see #setBorderColor(String) setBorderColor
** @see #setBorderStyle(String) setBorderStyle
** @see #setBackgroundColor(String) setBackgroundColor
** @see #setBorderWidth(String) setBorderWidth
** @see #setFontFamily(String) setFontFamily
**
**
**
*"""
"""
* Setting a CSS property to "" generally clears the
* attribute specification, restoring things to their initial
* defaults (not sure if this always works, but it appears to
* so far).
*
"""
USE_CSS = ""

"""*
** Keyword used to indicate that a curve should be
** displayed on the left y-axis.
**
** @see #Y2_AXIS Y2_AXIS
** @see GChart.Curve#setYAxis(GChart.YAxisId) setYAxis
**
*"""
Y_AXIS = YAxisId()

"""*
** Keyword used to indicate that a curve should be
** displayed on the right (the so-called y2) y-axis.
**
** @see #Y_AXIS Y_AXIS
** @see Curve#setYAxis setYAxis
**
*"""
Y2_AXIS = YAxisId()

"""*
** The default URL GChart will use to access the blank image
** (specifically, a 1 x 1 pixel transparent GIF) it requires
** to prevent "missing image" icons from appearing in your
** charts.
**
** @see #setBlankImageURL setBlankImageURL
**
*"""
DEFAULT_BLANK_IMAGE_URL = "gchart.gif"
"""*
** The full path to the default GChart blank image
** (specifically, a 1 x 1 pixel transparent GIF) it requires
** to prevent "missing image" icons from appearing in your
** charts.
** <p>
**
** Convenience constant equal to:
**
** <pre>
** pygwt.getModuleBaseURL()+GChart.DEFAULT_BLANK_IMAGE_URL
** </pre>
**
** @see #setBlankImageURL setBlankImageURL
**
*"""
DEFAULT_BLANK_IMAGE_URL_FULLPATH = pygwt.getImageBaseURL(True) + DEFAULT_BLANK_IMAGE_URL
DEFAULT_GRID_HEIGHT = DEFAULT_TICK_THICKNESS
DEFAULT_GRID_WIDTH = DEFAULT_TICK_THICKNESS
GRID_BORDER_STYLE = "solid"
GRID_BORDER_WIDTH = 1

"""* The default color used for all axes, gridlines, and ticks.
**
** @see #setGridColor setGridColor
**
"""
DEFAULT_GRID_COLOR = "black"


"""* The default thickness (height) of the rectangular region at
** the bottom of the chart allocated for footnotes, per
** <tt>&lt;br&gt;</tt> or <tt>&lt;li&gt;</tt> delimited HTML line. This
** default is only used when the footnote thickness is set to
** <tt>NAI</tt> (the default).
**
** @see #setChartFootnotesThickness setChartFootnotesThickness
**
"""
DEFAULT_FOOTNOTES_THICKNESS = 15

"""*
**
** The default thickness (height) of the rectangular region at
** the top of the chart allocated for the chart's title, per
** <tt>&lt;br&gt;</tt> or <tt>&lt;li&gt;</tt> delimited HTML line. This default
** is only used when the title thickness is set to
** <tt>NAI</tt>.
**
**
** @see #setChartTitleThickness setChartTitleThickness
**
"""
DEFAULT_TITLE_THICKNESS = 15



# for purposes of estimating fixed space "band" around the plot
# panel reserved for the tick labels:
TICK_CHARHEIGHT_TO_FONTSIZE_LOWERBOUND = 1.0
# a bit larger than the 0.6 rule-of-thumb
TICK_CHARWIDTH_TO_FONTSIZE_LOWERBOUND = 0.7
# For estimating size of invisible "box" needed for alignment
# purposes.  Note: when these are bigger, annotations remain
# properly aligned longer as user zooms up font sizes.  But,
# bigger bounding boxes can slow updates (not sure why,
# maybe it's related to hit testing browser has to do)
CHARHEIGHT_TO_FONTSIZE_UPPERBOUND = 2*1.5
CHARWIDTH_TO_FONTSIZE_UPPERBOUND = 2*0.7

TICK_BORDER_STYLE = GRID_BORDER_STYLE
TICK_BORDER_WIDTH = GRID_BORDER_WIDTH

# # of system curves "underneath" (before in DOM-order) user's curves
N_PRE_SYSTEM_CURVES = 16
# # of system curves "on top of" (after in DOM-order) user's curves
N_POST_SYSTEM_CURVES = 2
N_SYSTEM_CURVES = N_PRE_SYSTEM_CURVES+ N_POST_SYSTEM_CURVES
# index of curve that holds correspondingly-named chart part
# (sys curve indexes are negative & not directly developer-accessible)
PLOTAREA_ID = 0-N_SYSTEM_CURVES
TITLE_ID = 1-N_SYSTEM_CURVES
YAXIS_ID = 2-N_SYSTEM_CURVES
YTICKS_ID = 3-N_SYSTEM_CURVES
YGRIDLINES_ID = 4-N_SYSTEM_CURVES
YLABEL_ID = 5-N_SYSTEM_CURVES
Y2AXIS_ID = 6-N_SYSTEM_CURVES
Y2TICKS_ID = 7-N_SYSTEM_CURVES
Y2GRIDLINES_ID = 8-N_SYSTEM_CURVES
Y2LABEL_ID = 9-N_SYSTEM_CURVES
LEGEND_ID = 10-N_SYSTEM_CURVES
XAXIS_ID = 11-N_SYSTEM_CURVES
XTICKS_ID = 12-N_SYSTEM_CURVES
XGRIDLINES_ID = 13-N_SYSTEM_CURVES
XLABEL_ID = 14-N_SYSTEM_CURVES
FOOTNOTES_ID = 15-N_SYSTEM_CURVES
HOVER_CURSOR_ID = 16-N_SYSTEM_CURVES
HOVER_ANNOTATION_ID = 17-N_SYSTEM_CURVES

