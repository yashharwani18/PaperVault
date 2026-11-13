package org.localknowledge.library;

import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.nio.*;
import java.nio.channels.FileChannel;
import java.util.*;
import org.json.*;

/** Host-only runner: calls production parsing code without copying private data to APK assets. */
public final class PhoneCorpusProbe {
    public static void main(String[] args) throws Exception {
        if(args[0].equals("--rank")) {
            List<String> keys=Files.readAllLines(Path.of(args[1]),StandardCharsets.UTF_8);
            JSONArray results=new JSONArray();
            try(FileChannel file=FileChannel.open(Path.of(args[2]),StandardOpenOption.READ)) {
                ByteBuffer scores=file.map(FileChannel.MapMode.READ_ONLY,0,file.size()).order(ByteOrder.LITTLE_ENDIAN);
                while(scores.hasRemaining()) {
                    PageCandidates<Integer> top=new PageCandidates<>(20);
                    for(int i=0;i<keys.size();i++)top.add(keys.get(i),scores.getDouble(),i);
                    List<Integer> ranked=top.values();results.put(new JSONArray(ranked.subList(0,Math.min(5,ranked.size()))));
                }
            }
            System.out.println(results);return;
        }
        List<JSONObject> pages=new ArrayList<>();
        for(String line:Files.readAllLines(Path.of(args[0]),StandardCharsets.UTF_8))
            if(!line.isBlank())pages.add(new JSONObject(line));
        JSONArray results=new JSONArray();
        for(String line:Files.readAllLines(Path.of(args[1]),StandardCharsets.UTF_8)) {
            JSONObject test=new JSONObject(line);String query=test.getString("query"),wanted=InvoiceNumbers.query(query);
            JSONArray matches=new JSONArray();
            if(wanted!=null)for(JSONObject page:pages)
                if(InvoiceNumbers.matches(wanted,"",page.getString("text")))
                    matches.put(page.getString("document_id")+":"+page.getInt("page_number"));
            results.put(new JSONObject().put("query",query).put("parsed",wanted==null?JSONObject.NULL:wanted).put("pages",matches));
        }
        System.out.println(results);
    }
}
