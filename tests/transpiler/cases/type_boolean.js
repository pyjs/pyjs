export function main() {
    console.log(false + 1);
    console.log(1 + false);
    console.log(true - 1);
    console.log(1 - true);
    console.log(false + false);
    console.log(true + true);
    console.log(true + false);
    console.log(true * 3);
    console.log((false + 1) * 3);
    console.log((true === true ? 'True' : 'False'));
    console.log((false === false ? 'True' : 'False'));
    console.log((true == true ? 'True' : 'False'));
    console.log((true == 1 ? 'True' : 'False'));
    console.log((true === Boolean(1) ? 'True' : 'False'));
    console.log((false == false ? 'True' : 'False'));
    console.log((false == 0 ? 'True' : 'False'));
    console.log((false === Boolean(0) ? 'True' : 'False'));
    console.log((true != false ? 'True' : 'False'));
    console.log((true !== false ? 'True' : 'False'));
    console.log((false !== true ? 'True' : 'False'));
    var a = false;
    console.log((a ? 'True' : 'False'));
    console.log(((value)=>value<0?'-0b'+(-value).toString(2):'0b'+value.toString(2))(Number(a)));
    console.log(((value)=>value<0?'-0o'+(-value).toString(8):'0o'+value.toString(8))(Number(a)));
    console.log(((value)=>value<0?'-0x'+(-value).toString(16):'0x'+value.toString(16))(Number(a)));
    a = true;
    console.log((a ? 'True' : 'False'));
    console.log(((value)=>value<0?'-0b'+(-value).toString(2):'0b'+value.toString(2))(Number(a)));
    console.log(((value)=>value<0?'-0o'+(-value).toString(8):'0o'+value.toString(8))(Number(a)));
    console.log(((value)=>value<0?'-0x'+(-value).toString(16):'0x'+value.toString(16))(Number(a)));
    if (a) {
        console.log('a is true');
    }
    if (!a) {
        console.log('should not print');
    } else {
        console.log('else a is true');
    }
}
