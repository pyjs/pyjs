
def create_xml_doc(text):
    JS("""
try //Internet Explorer
  {
  var xmlDoc=new ActiveXObject("Microsoft['XMLDOM']");
  xmlDoc['async']="false";
  xmlDoc['loadXML'](@{{text}});
  }
catch(e)
  {
  try //Firefox, Mozilla, Opera, etc.
    {
    var parser=new DOMParser();
    xmlDoc=parser['parseFromString'](@{{text}},"text/xml");
    }
  catch(e)
  {
    return null;
  }
  }
  return xmlDoc;
  """)

