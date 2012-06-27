# pysm_print_fn is actually in pysmrun.py and is added using add_global()
def printFunc(objs, newline):
    JS("""
        var s = "";
        for(var i=0; i < @{{objs}}['length']; i++) {
            if(s != "") s += " ";
                s += @{{objs}}[i];
        }

        pysm_print_fn(s);
    """)

# pysm_import_module is in pysmrun.py and has been added using add_global()
def import_module(syspath, parent_name, module_name, dynamic_load, async, init):
    pysm_import_module(parent_name, module_name)
