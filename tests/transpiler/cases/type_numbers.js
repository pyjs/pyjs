import { float_string as $float_string } from './pyjs.python.js';

export function main() {
    var a = 9;
    console.log(a);
    console.log(1 + 1);
    console.log(1 + (2 + 3));
    a = a + 2;
    console.log(a);
    console.log(7 - 5);
    console.log(7 - 5 - 1);
    console.log(7 - (5 - 1));
    a = a - 5;
    console.log(a);
    console.log(2 * 3);
    console.log(0 * 3);
    a = a * 2;
    console.log(a);
    a = 5;
    console.log(5 ** 2);
    a = a ** 2;
    console.log(a);
    console.log($float_string(((left,right)=>{if(right===0)throw new Error('division by zero');return left/right;})(5,2)));
    console.log(((left,right)=>{if(right===0)throw new Error('division by zero');return Math.floor(left/right);})(5,2));
    var divided = 5.0;
    divided = ((left,right)=>{if(right===0)throw new Error('division by zero');return left/right;})(divided,2);
    console.log($float_string(divided));
    a = 5;
    a = ((left,right)=>{if(right===0)throw new Error('division by zero');return Math.floor(left/right);})(a,2);
    console.log(a);
    console.log((((value)=>typeof value==='boolean'||Number.isInteger(value))(a) ? 'True' : 'False'));
    a = 11;
    console.log(a);
    console.log(((value)=>value<0?'-0b'+(-value).toString(2):'0b'+value.toString(2))(a));
    console.log(((value)=>value<0?'-0o'+(-value).toString(8):'0o'+value.toString(8))(a));
    console.log(((value)=>value<0?'-0x'+(-value).toString(16):'0x'+value.toString(16))(a));
}
