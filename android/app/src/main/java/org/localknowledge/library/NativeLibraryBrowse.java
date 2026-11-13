package org.localknowledge.library;

import android.database.Cursor;
import org.json.*;
import java.io.File;
import java.text.Normalizer;
import java.util.*;
import java.util.regex.*;

/** Incremental metadata query path. Does not read document text or invoke models. */
final class NativeLibraryBrowse {
 static JSONObject page(NativeBackend backend,JSONObject body)throws Exception {return page(backend,body,false);}
 static Set<String> scopeIds(NativeBackend backend,JSONObject filters)throws Exception {
  Set<String> keys=new HashSet<>(Arrays.asList("extension","status","added_from","added_through","min_size","max_size","favorites","recent","name"));Iterator<String> it=filters.keys();while(it.hasNext())if(!keys.contains(it.next()))throw new IllegalArgumentException("Unsupported library search filter.");
  return NativeBackend.strings(page(backend,filters,true).getJSONArray("ids"));
 }
 static JSONObject page(NativeBackend backend,JSONObject body,boolean idsOnly)throws Exception {
  Map<String,String> orders=Map.of("added_new","d.created_at DESC,d.id ASC","added_old","d.created_at ASC,d.id ASC","size_large","d.size_bytes DESC,d.id ASC","size_small","d.size_bytes ASC,d.id ASC","name","d.id ASC","name_desc","d.id ASC");
  String sort=body.optString("sort","added_new"),order=orders.get(sort);if(order==null)throw new IllegalArgumentException("This sort is not yet available for database browsing.");
  int limit=integer(body,"limit",100),offset=integer(body,"offset",0);if(limit<1||limit>100||offset<0||offset>1000000)throw new IllegalArgumentException("Choose a valid document page.");
  StringBuilder where=new StringBuilder(" WHERE d.trashed=0");List<String> args=new ArrayList<>();String folder=body.optString("folder_id","");
  if(!folder.isEmpty()){backend.store.one("SELECT id FROM folders WHERE id=?",folder);where.append(" AND d.folder_id=?");args.add(folder);}
  String extension=body.optString("extension","");if(!extension.isEmpty()){
   if(extension.length()>16||!extension.codePoints().allMatch(Character::isLetterOrDigit))throw new IllegalArgumentException("Choose a valid document type.");
   String suffix="."+extension.toLowerCase(Locale.ROOT);where.append(" AND lower(substr(d.filename,-?))=?");args.add(String.valueOf(suffix.codePointCount(0,suffix.length())));args.add(suffix);
  }
  String status=body.optString("status","all");if(status.equals("indexed"))where.append(" AND d.status='indexed'");else if(status.equals("attention"))where.append(" AND d.status!='indexed'");else if(!status.equals("all"))throw new IllegalArgumentException("Choose a valid status filter.");
  for(String key:new String[]{"added_from","added_through"})if(body.has(key)&&!body.optString(key).isEmpty()){String date=body.getString(key);try{if(!date.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}")||!java.time.LocalDate.parse(date).toString().equals(date))throw new IllegalArgumentException();}catch(RuntimeException error){throw new IllegalArgumentException("Choose a valid date.");}where.append(" AND d.created_at").append(key.equals("added_from")?">=":"<=").append("?");args.add(key.equals("added_through")?date+"\uffff":date);}
  for(String key:new String[]{"min_size","max_size"})if(body.has(key)&&!body.isNull(key)&&!body.optString(key).isEmpty()){long size=longInteger(body,key);if(size<0)throw new IllegalArgumentException("Choose a valid file size.");where.append(" AND d.size_bytes").append(key.equals("min_size")?">=":"<=").append("?");args.add(String.valueOf(size));}
  Set<String> allowed=null;String linked=body.optString("linked_folder_id","");
  if(!linked.isEmpty()){
   for(JSONObject group:LibraryStore.objects(backend.features.groups()))if(group.optString("id").equals(linked)){allowed=new HashSet<>(NativeBackend.strings(group.optJSONArray("document_ids")));break;}
   if(allowed==null)throw new IllegalArgumentException("Folder changed. Refresh the library.");
  }
  for(String key:new String[]{"favorites","recent"})if(body.has(key)&&!(body.opt(key) instanceof Boolean))throw new IllegalArgumentException("Choose a valid reading filter.");
  if(body.optBoolean("favorites")||body.optBoolean("recent")){
   JSONObject reading=backend.libraryQoL.state();
   if(body.optBoolean("favorites")){Set<String> favorites=new HashSet<>();JSONObject values=reading.getJSONObject("documents");Iterator<String> ids=values.keys();while(ids.hasNext()){String id=ids.next();if(values.getJSONObject(id).optBoolean("favorite"))favorites.add(id);}if(allowed==null)allowed=favorites;else allowed.retainAll(favorites);}
   if(body.optBoolean("recent")){Set<String> recent=new HashSet<>(NativeBackend.strings(reading.optJSONArray("recent_ids")));if(allowed==null)allowed=recent;else allowed.retainAll(recent);}
  }
  String name=body.optString("name","").toLowerCase(Locale.ROOT);if(name.length()>500)throw new IllegalArgumentException("Choose a valid filename filter.");
  Map<String,String> names=new HashMap<>();if(!name.isEmpty())for(JSONObject row:LibraryStore.objects(backend.store.query("SELECT key,value FROM settings WHERE key LIKE 'khoj.name:%'")))names.put(row.optString("key").substring("khoj.name:".length()),row.optString("value"));
  String base=" FROM documents d JOIN folders f ON f.id=d.folder_id"+where;JSONArray documents;int total;PhoneScan.ExclusionRules rules=backend.phoneScan.exclusionRules();
  List<String[]> indexRows=new ArrayList<>();
  boolean plain=!rules.invalid&&rules.rules.isEmpty()&&allowed==null&&name.isEmpty();
  if(idsOnly&&plain){
   JSONArray ids=new JSONArray();try(Cursor c=backend.store.getReadableDatabase().rawQuery("SELECT d.id"+base,args.toArray(new String[0]))){while(c.moveToNext()){NativeBackend.searchCheckpoint();ids.put(c.getString(0));}}return Json.obj("ids",ids);
  }
  // Name sorts use the natural comparator below before slicing the page.
  // The SQL order for names is only an id fallback, not filename order.
  if(!idsOnly&&plain&&!sort.equals("name")&&!sort.equals("name_desc")){
   total=backend.store.one("SELECT count(*) n"+base,args.toArray(new String[0])).getInt("n");List<String> pageArgs=new ArrayList<>(args);pageArgs.add(String.valueOf(limit));pageArgs.add(String.valueOf(offset));
   documents=backend.store.query("SELECT d.*,f.name folder_name"+base+" ORDER BY "+order+" LIMIT ? OFFSET ?",pageArgs.toArray(new String[0]));
   try(Cursor c=backend.store.getReadableDatabase().rawQuery("SELECT d.id,d.filename"+base,args.toArray(new String[0]))){while(c.moveToNext()){NativeBackend.searchCheckpoint();indexRows.add(new String[]{c.getString(0),c.getString(1)});}}
  }else{
   documents=new JSONArray();total=0;boolean collect=!idsOnly&&(sort.equals("name")||sort.equals("name_desc"));List<JSONObject> collected=collect?new ArrayList<>():null;
   try(Cursor c=backend.store.getReadableDatabase().rawQuery("SELECT d.*,f.name folder_name"+base+" ORDER BY "+order,args.toArray(new String[0]))){while(c.moveToNext()){
    String mode=c.getString(c.getColumnIndexOrThrow("source_mode")),path=c.getString(c.getColumnIndexOrThrow("source_path"));if("reference".equals(mode)&&backend.phoneScan.isExcluded(new File(path)))continue;
    String id=c.getString(c.getColumnIndexOrThrow("id"));if(allowed!=null&&!allowed.contains(id))continue;
    String filename=c.getString(c.getColumnIndexOrThrow("filename"));
    if(!name.isEmpty()){String title=names.get(id);if(title==null||title.trim().isEmpty())title=c.getString(c.getColumnIndexOrThrow("title"));if(!((title==null?"":title)+" "+(filename==null?"":filename)).toLowerCase(Locale.ROOT).contains(name))continue;}
    NativeBackend.searchCheckpoint();indexRows.add(new String[]{id,filename});if(idsOnly){documents.put(id);total++;continue;}
    if(collect){collected.add(row(c));total++;continue;}
    if(total>=offset&&documents.length()<limit)documents.put(row(c));total++;
   }}
   if(collect){collected.sort((left,right)->{int comparison=sortKey(left.optString("filename")).compareTo(sortKey(right.optString("filename")));if(comparison==0)comparison=left.optString("id").compareTo(right.optString("id"));return sort.equals("name_desc")?-comparison:comparison;});for(int i=offset;i<Math.min(collected.size(),offset+limit);i++)documents.put(collected.get(i));}
  }
  if(idsOnly)return Json.obj("ids",documents);
  JSONObject index=index(indexRows);
  backend.phoneScan.attachModifiedTimes(documents);for(JSONObject doc:LibraryStore.objects(documents))NativeBackend.decorateTextSource(doc);
  return Json.obj("documents",backend.features.decorate(documents),"total",total,"offset",offset,"limit",limit,"letters",index.getJSONArray("letters"),"types",index.getJSONArray("types"));
 }
 static JSONObject row(Cursor cursor)throws JSONException {JSONObject row=new JSONObject();for(int i=0;i<cursor.getColumnCount();i++){Object value=cursor.isNull(i)?JSONObject.NULL:cursor.getType(i)==Cursor.FIELD_TYPE_INTEGER?cursor.getLong(i):cursor.getType(i)==Cursor.FIELD_TYPE_FLOAT?cursor.getDouble(i):cursor.getType(i)==Cursor.FIELD_TYPE_BLOB?JSONObject.NULL:cursor.getString(i);row.put(cursor.getColumnName(i),value);}return row;}
 /** Natural-order offsets and the type list; mirrors the desktop page index. */
 static JSONObject index(List<String[]> rows)throws JSONException {
  rows.sort((left,right)->{int order=sortKey(left[1]).compareTo(sortKey(right[1]));return order!=0?order:left[0].compareTo(right[0]);});
  JSONArray letters=new JSONArray();Set<String> seen=new HashSet<>();
  for(int i=0;i<rows.size();i++){String value=letter(rows.get(i)[1]);if(seen.add(value))letters.put(Json.obj("letter",value,"offset",i));}
  Set<String> types=new TreeSet<>();for(String[] row:rows){String value=extension(row[1]);if(!value.isEmpty())types.add(value);}
  JSONArray typeArray=new JSONArray();for(String type:types)typeArray.put(type);
  return Json.obj("letters",letters,"types",typeArray);
 }
 static String sortKey(String value){
  String text=Normalizer.normalize(value==null?"":value.trim(),Normalizer.Form.NFKD).replaceAll("\\p{M}+","").toLowerCase(Locale.ROOT);
  StringBuilder key=new StringBuilder();Matcher matcher=Pattern.compile("\\d+|\\D+").matcher(text);
  while(matcher.find()){
   String token=matcher.group();
   if(token.matches("\\d+")){String digits=token.replaceFirst("^0+(?!$)","");key.append('\u0001').append(String.format(Locale.ROOT,"%020d",digits.length())).append(digits).append('\u0002');}
   else key.append(token);
  }
  return key.toString();
 }
 static String letter(String filename){
  String value=filename==null?"":Normalizer.normalize(filename.trim(),Normalizer.Form.NFKC);
  if(value.isEmpty())return "#";
  String first=value.substring(0,value.offsetByCodePoints(0,1)).toUpperCase(Locale.ROOT);
  return first.length()==1&&first.charAt(0)>='A'&&first.charAt(0)<='Z'?first:"#";
 }
 static String extension(String filename){
  String value=filename==null?"":filename;int dot=value.lastIndexOf('.');
  return dot>0&&dot<value.length()-1?value.substring(dot+1).toLowerCase(Locale.ROOT):"";
 }
 static long longInteger(JSONObject body,String key)throws JSONException {Object value=body.get(key);if(!(value instanceof Integer)&&!(value instanceof Long))throw new IllegalArgumentException("Choose a valid number.");return ((Number)value).longValue();}
 static int integer(JSONObject body,String key,int fallback)throws JSONException {if(!body.has(key)||body.isNull(key))return fallback;long n=longInteger(body,key);if(n<Integer.MIN_VALUE||n>Integer.MAX_VALUE)throw new IllegalArgumentException("Choose a valid number.");return (int)n;}
}
