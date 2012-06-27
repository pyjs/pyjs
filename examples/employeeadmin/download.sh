#!/bin/sh

prompt_download( ) {
	if [ -z "$DOWNLOADS" ] ; then
		cat <<EOM
Use --downloads-yes to automatically answer the next prompt with 'yes' and
use --downloads-no to automatically answer the next prompt with 'no'
EOM
	fi
	while [ "$DOWNLOADS" != "no" -a "$DOWNLOADS" != "yes" ] ; do
		read -p "Download PureMVC? (yes/no) " DOWNLOADS
	done
	if [ "$DOWNLOADS" = "yes" ] ; then
		return 0;
	fi
	return 1
}
get_puremvc ( ) {
	URL="http://puremvc.org/pages/downloads/Python/PureMVC_Python.zip"
	if which wget >/dev/null ; then
		wget -O PureMVC_Python.zip "$URL"
	elif which curl >/dev/null ; then
		curl -o PureMVC_Python.zip "$URL"
	else
		echo "No wget/curl found" >&2
		exit 1
	fi
}
if [ ! -f PureMVC_Python_1_2/src/puremvc/__init__.py ] ; then
	if prompt_download ; then
		get_puremvc
	else
		echo "Will not download PureMVC" >&2
		exit 1
	fi
	if ! unzip PureMVC_Python.zip ; then
		echo "Cannot unzip PureMVC_Python.zip" >&2
		exit 1
	fi
	if [ ! -f PureMVC_Python_1_2/src/puremvc/__init__.py ] ; then
		echo "Something went wrong...."
		exit 1
	fi
fi
exit 0
