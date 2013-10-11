#!/bin/sh
# Copyright (C) 2011, Kees Bos <cornelis.bos@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

if [ "$1" == '-n' ] ; then
	ACTION="echo rm"
	shift
else
	ACTION=rm
fi
if [ $# -eq 0 ] ; then
	echo "usage: $0 [-n] all|js|patch|complete" >&2
	exit 1
fi

clean_js( ) {
	git clean -n|awk '/Would remove .*[.]js$/ {print $3}'|xargs ${ACTION}
}

clean_pyc( ) {
	git clean -n|awk '/Would remove .*[.]pyc$/ {print $3}'|xargs ${ACTION}
}

clean_patch( ) {
	git clean -n|awk '/Would remove .*[.](rej)|(orig)$/ {print $3}'|xargs ${ACTION}
}

for WHAT in $* ; do
	case ${WHAT} in
	js)
		clean_js
		;;
	pyc)
		clean_pyc
		;;
	patch)
		clean_patch
		;;
	all)
		clean_js
		clean_pyc
		clean_patch
		;;
	complete)
		if [ ! -d .git ] ; then
			echo "Cannot find .git directory to be removed." >&2
			echo "Switch to root directory of repository." >&2
			exit 1
		fi
		if [ ${ACTION} == 'rm' ] ; then
			git-clean -f -d -x
			rm -rf .git
		else
			git-clean -n -d -x
		fi
	esac
done
