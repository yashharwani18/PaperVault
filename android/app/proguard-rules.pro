# Native entry points use fixed JNI names. JavaScript calls these bridge methods.
-keep class org.localknowledge.library.NativeModels { *; }
-keepclassmembers class * { @android.webkit.JavascriptInterface <methods>; }
-keepattributes Signature,InnerClasses,EnclosingMethod,*Annotation*
# PDFBox loads font/codec implementations and resources by their original names.
-keep class com.tom_roush.** { *; }
-dontwarn java.awt.**
-dontwarn javax.imageio.**
-dontwarn org.bouncycastle.**
# PDFBox's optional JPEG-2000 codec is not part of this distribution.
-dontwarn com.gemalto.jp2.JP2Decoder
-dontwarn com.gemalto.jp2.JP2Encoder
