Package the web/ PWA into this folder for the Android WebView shell:

  rsync -a --delete web/ android/app/src/main/assets/www/

MainActivity loads file:///android_asset/www/index.html
