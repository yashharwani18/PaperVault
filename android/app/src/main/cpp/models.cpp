#include <jni.h>
#include <llama.h>
#include <ggml-backend.h>
#include <string>
#include <vector>
#include <mutex>
#include <cmath>
#include <stdexcept>
#include <chrono>
#include <thread>
#include <deque>
#include <android/log.h>

static std::mutex guard;
static llama_model * model=nullptr;
static llama_model * vocabulary_model=nullptr;static std::string vocabulary_path;
static std::string loaded;
static bool initialized=false;
static bool batch_qualified=false,batch_rejected=false;
static std::string native_directory;
static jlong embedding_calls=0,embedding_micros=0,context_creations=0,model_loads=0;
static jlong embedding_batches=0,embedding_tokens=0;
using Clock=std::chrono::steady_clock;
static llama_context *embedding_context=nullptr;
static size_t embedding_capacity=0;
// PageIndexer checks up to four passages before embedding them. Reuse those
// exact token IDs without changing chunk boundaries or the embedding recipe.
static std::deque<std::pair<std::string,std::vector<llama_token>>> token_cache;
// The reused context retains this callback pointer between calls.
static Clock::time_point embedding_deadline;
static void clear_embedding(){if(embedding_context)llama_free(embedding_context);embedding_context=nullptr;embedding_capacity=0;}
static bool expired(void *data){return Clock::now()>*static_cast<Clock::time_point*>(data);}
static int threads(){return std::max(1u,std::min(4u,std::thread::hardware_concurrency()));}
static std::string str(JNIEnv *e,jstring s) { const char *p=e->GetStringUTFChars(s,nullptr);std::string v(p);e->ReleaseStringUTFChars(s,p);return v; }
static void fail(JNIEnv *e,const char *msg) { e->ThrowNew(e->FindClass("java/lang/IllegalStateException"),msg); }
static void load(const std::string &path) {
    if(!initialized){
        if(native_directory.empty())throw std::runtime_error("Local CPU backend directory is unavailable");
        ggml_backend_load_all_from_path(native_directory.c_str());
        if(ggml_backend_dev_count()==0)throw std::runtime_error("No compatible local CPU backend was found");
        llama_backend_init();initialized=true;
    }
    if(model&&loaded==path)return;
    token_cache.clear();batch_qualified=false;batch_rejected=false;
    clear_embedding();
    if(model){llama_model_free(model);model=nullptr;loaded.clear();}
    auto p=llama_model_default_params();p.n_gpu_layers=0;p.load_mode=LLAMA_LOAD_MODE_MMAP;
    model=llama_model_load_from_file(path.c_str(),p);
    if(!model)throw std::runtime_error("Could not load bundled local model");
    model_loads++;
    loaded=path;
}
static std::vector<llama_token> tokens(const std::string &text,int known_count=0) {
    for(const auto &entry:token_cache)if(entry.first==text)return entry.second;
    auto *vocab=llama_model_get_vocab(model);
    int n=known_count?known_count:-llama_tokenize(vocab,text.data(),text.size(),nullptr,0,true,true);
    if(n<=0||n>8192)throw std::runtime_error("Input token limit exceeded");
    std::vector<llama_token> out(n);
    n=llama_tokenize(vocab,text.data(),text.size(),out.data(),out.size(),true,true);
    if(n<0)throw std::runtime_error("Could not tokenize local input");out.resize(n);
    if(token_cache.size()>=8)token_cache.pop_front();
    token_cache.emplace_back(text,out);return out;
}
extern "C" JNIEXPORT void JNICALL Java_org_localknowledge_library_NativeModels_configure(JNIEnv *e,jclass,jstring directory){std::lock_guard<std::mutex> lock(guard);native_directory=str(e,directory);llama_log_set([](enum ggml_log_level level,const char *message,void*){if(level==GGML_LOG_LEVEL_ERROR||level==GGML_LOG_LEVEL_WARN)__android_log_write(ANDROID_LOG_WARN,"KhojNative",message);},nullptr);}
extern "C" JNIEXPORT jstring JNICALL Java_org_localknowledge_library_NativeModels_cpuInfo(JNIEnv *e,jclass){std::lock_guard<std::mutex> lock(guard);std::string info=initialized?llama_print_system_info():"CPU backend not loaded yet";
#ifdef KHOJ_EXPERIMENTAL_NATIVE_BATCHES
    info+=" KHOJ_NATIVE_BATCHES = 1";info+=batch_rejected?" BATCH_QUALIFICATION = rejected":batch_qualified?" BATCH_QUALIFICATION = passed":" BATCH_QUALIFICATION = pending";
#else
    info+=" KHOJ_NATIVE_BATCHES = 0";
#endif
    return e->NewStringUTF(info.c_str());}
extern "C" JNIEXPORT jlongArray JNICALL Java_org_localknowledge_library_NativeModels_performance(JNIEnv *e,jclass){std::lock_guard<std::mutex> lock(guard);jlong values[]={embedding_calls,embedding_micros,context_creations,model_loads,embedding_batches,embedding_tokens};auto result=e->NewLongArray(6);e->SetLongArrayRegion(result,0,6,values);return result;}

// Called with guard held; independent sequence IDs prevent cross-passage attention.
static std::vector<std::vector<float>> embeddings_raw(const std::string &path,const std::vector<std::string> &inputs){
    if(inputs.empty()||inputs.size()>4)throw std::runtime_error("Embedding batch must contain 1 to 4 passages");
#ifndef KHOJ_EXPERIMENTAL_NATIVE_BATCHES
    // Multi-sequence Q8 inference failed our cache-compatibility gate. Preserve
    // the scalar recipe in release builds; retain an explicit benchmark switch.
    if(inputs.size()>1){std::vector<std::vector<float>> out;for(const auto &input:inputs){auto one=embeddings_raw(path,{input});out.push_back(std::move(one[0]));}return out;}
#endif
    auto started=Clock::now();load(path);
    std::vector<std::vector<llama_token>> encoded;int total=0;
    for(const auto &input:inputs){auto t=tokens(input);if(t.size()>512)throw std::runtime_error("Embedding passage exceeds 512 tokens; split it further");total+=t.size();encoded.push_back(std::move(t));}
    // Align real sequences with the pinned 64-token attention tiles. Padding
    // gets separate sequence IDs, participates only in its own attention/pool,
    // and is never returned as a document embedding.
    int actual_tokens=total;std::vector<int> padding(inputs.size(),0);if(inputs.size()>1&&encoded[0].size()>=64){for(size_t i=0;i+1<inputs.size();i++){padding[i]=(64-encoded[i].size()%64)%64;total+=padding[i];}}
    embedding_deadline=Clock::now()+std::chrono::seconds(90);
    if(!embedding_context||embedding_capacity<inputs.size()){
        clear_embedding();auto p=llama_context_default_params();
        int slots=inputs.size()==1?1:2*inputs.size();p.n_ctx=512*slots;p.n_batch=p.n_ctx;p.n_ubatch=p.n_ctx;p.n_seq_max=slots;p.kv_unified=true;
        p.n_threads=threads();p.n_threads_batch=threads();p.embeddings=true;p.pooling_type=LLAMA_POOLING_TYPE_MEAN;p.abort_callback=expired;p.abort_callback_data=&embedding_deadline;
        embedding_context=llama_init_from_model(model,p);if(!embedding_context)throw std::runtime_error("Could not allocate embedding context");
        embedding_capacity=inputs.size();context_creations++;
    }
    auto *ctx=embedding_context;if(auto memory=llama_get_memory(ctx))llama_memory_clear(memory,true);
    auto batch=llama_batch_init(total,0,1);batch.n_tokens=total;
    std::vector<std::vector<float>> result;
    try{
        int offset=0;for(size_t seq=0;seq<encoded.size();seq++){for(size_t pos=0;pos<encoded[seq].size();pos++,offset++){
            batch.token[offset]=encoded[seq][pos];batch.pos[offset]=pos;batch.n_seq_id[offset]=1;batch.seq_id[offset][0]=seq;batch.logits[offset]=true;
        }for(int pad=0;pad<padding[seq];pad++,offset++){batch.token[offset]=encoded[seq][0];batch.pos[offset]=pad;batch.n_seq_id[offset]=1;batch.seq_id[offset][0]=inputs.size()+seq;batch.logits[offset]=true;}}
        if((llama_model_has_encoder(model)?llama_encode(ctx,batch):llama_decode(ctx,batch))!=0)throw std::runtime_error("Local embedding failed");
        int dimensions=llama_model_n_embd_out(model);if(dimensions!=768)throw std::runtime_error("Unexpected embedding dimensions");
        for(size_t seq=0;seq<inputs.size();seq++){
            auto *values=llama_get_embeddings_seq(ctx,seq);if(!values)throw std::runtime_error("No pooled embedding returned");
            std::vector<float> out(values,values+dimensions);double norm=0;for(float v:out)norm+=v*v;norm=sqrt(norm);
            if(!std::isfinite(norm)||norm==0)throw std::runtime_error("Invalid embedding");for(float &v:out)v/=norm;result.push_back(std::move(out));
        }
    }catch(...){llama_batch_free(batch);throw;}
    llama_batch_free(batch);embedding_calls+=inputs.size();embedding_batches++;embedding_tokens+=actual_tokens;
    embedding_micros+=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-started).count();return result;
}
// Preserve the scalar CPU attention kernel: the pinned ggml backend switches
// from an F16 accumulator to tiled F32 attention at 64 query tokens. Packing
// short and long sequences together changes vectors even with correct masks.
static std::vector<std::vector<float>> embeddings(const std::string &path,const std::vector<std::string> &inputs){
#ifndef KHOJ_EXPERIMENTAL_NATIVE_BATCHES
    return embeddings_raw(path,inputs);
#else
    if(inputs.empty()||inputs.size()>4)throw std::runtime_error("Embedding batch must contain 1 to 4 passages");
    load(path);if(batch_rejected){std::vector<std::vector<float>> scalar;for(const auto &text:inputs)scalar.push_back(embeddings_raw(path,{text})[0]);return scalar;}std::vector<size_t> large,small;std::vector<int> lengths;
    for(size_t i=0;i<inputs.size();i++){int n=tokens(inputs[i]).size();if(n>512)throw std::runtime_error("Embedding passage exceeds 512 tokens; split it further");lengths.push_back(n);(n>=64?large:small).push_back(i);}
    std::vector<std::vector<float>> result(inputs.size());bool used_multi=false;
    auto run=[&](const std::vector<size_t> &indices){if(indices.empty())return;std::vector<std::string> texts;for(auto i:indices)texts.push_back(inputs[i]);used_multi|=texts.size()>1;auto out=embeddings_raw(path,texts);for(size_t j=0;j<indices.size();j++)result[indices[j]]=std::move(out[j]);};
    run(large);std::vector<size_t> group;int count=0;
    for(auto i:small){if(count+lengths[i]>=64){run(group);group.clear();count=0;}group.push_back(i);count+=lengths[i];}run(group);
    // ARM kernels vary across phones. Qualify once per loaded model using the
    // actual passages; incompatible devices retain scalar outputs and execution.
    if(used_multi&&!batch_qualified){
        std::vector<std::vector<float>> scalar;bool good=true;
        for(size_t i=0;i<inputs.size();i++){
            auto reference=embeddings_raw(path,{inputs[i]})[0];double dot=0,aa=0,bb=0,max_error=0;
            for(size_t j=0;j<reference.size();j++){double a=reference[j],b=result[i][j];dot+=a*b;aa+=a*a;bb+=b*b;max_error=std::max(max_error,std::abs(a-b));}
            good&=std::isfinite(bb)&&std::abs(bb-1)<0.001&&dot/std::sqrt(aa*bb)>=0.99999&&max_error<=0.0001;scalar.push_back(std::move(reference));
        }
        batch_qualified=good;batch_rejected=!good;
        __android_log_write(good?ANDROID_LOG_INFO:ANDROID_LOG_WARN,"KhojBatch",good?"Native batch scalar-compatibility check passed":"Native batch compatibility rejected; using scalar inference");
        if(!good)return scalar;
    }
    return result;
#endif
}
extern "C" JNIEXPORT jint JNICALL Java_org_localknowledge_library_NativeModels_tokenCountNative(JNIEnv *e,jclass,jstring path,jstring input){std::lock_guard<std::mutex> lock(guard);try{load(str(e,path));auto text=str(e,input);for(const auto &entry:token_cache)if(entry.first==text)return entry.second.size();int n=-llama_tokenize(llama_model_get_vocab(model),text.data(),text.size(),nullptr,0,true,true);if(n<=0)throw std::runtime_error("Could not count local input tokens");return n>512?n:tokens(text,n).size();}catch(const std::exception &error){fail(e,error.what());return 0;}}
extern "C" JNIEXPORT jfloatArray JNICALL Java_org_localknowledge_library_NativeModels_embedNative(JNIEnv *e,jclass,jstring path,jstring input){std::lock_guard<std::mutex> lock(guard);try{auto out=embeddings(str(e,path),{str(e,input)});auto result=e->NewFloatArray(768);e->SetFloatArrayRegion(result,0,768,out[0].data());return result;}catch(const std::exception &error){clear_embedding();fail(e,error.what());return nullptr;}}
extern "C" JNIEXPORT jobjectArray JNICALL Java_org_localknowledge_library_NativeModels_embedBatchNative(JNIEnv *e,jclass,jstring path,jobjectArray inputs){
    std::lock_guard<std::mutex> lock(guard);try{
        if(!inputs)throw std::runtime_error("Embedding inputs are missing");int count=e->GetArrayLength(inputs);if(count<1||count>4)throw std::runtime_error("Embedding batch must contain 1 to 4 passages");
        std::vector<std::string> text;for(int i=0;i<count;i++){auto item=static_cast<jstring>(e->GetObjectArrayElement(inputs,i));if(!item)throw std::runtime_error("Embedding input is missing");text.push_back(str(e,item));e->DeleteLocalRef(item);}
        auto out=embeddings(str(e,path),text);auto result=e->NewObjectArray(count,e->FindClass("[F"),nullptr);
        for(int i=0;i<count;i++){auto row=e->NewFloatArray(768);e->SetFloatArrayRegion(row,0,768,out[i].data());e->SetObjectArrayElement(result,i,row);e->DeleteLocalRef(row);}return result;
    }catch(const std::exception &error){clear_embedding();fail(e,error.what());return nullptr;}
}
extern "C" JNIEXPORT jint JNICALL Java_org_localknowledge_library_NativeModels_tokenCountVocabulary(JNIEnv *e,jclass,jstring path,jstring input){
    std::lock_guard<std::mutex> lock(guard);try{
        auto file=str(e,path);if(!vocabulary_model||vocabulary_path!=file){if(vocabulary_model)llama_model_free(vocabulary_model);vocabulary_model=nullptr;vocabulary_path.clear();auto p=llama_model_default_params();p.vocab_only=true;vocabulary_model=llama_model_load_from_file(file.c_str(),p);if(!vocabulary_model)throw std::runtime_error("Could not load verified text tokenizer");vocabulary_path=file;}
        std::string text;const jchar *chars=e->GetStringChars(input,nullptr);int size=e->GetStringLength(input);
        for(int i=0;i<size;i++){uint32_t cp=chars[i];if(cp>=0xD800&&cp<=0xDBFF&&i+1<size&&chars[i+1]>=0xDC00&&chars[i+1]<=0xDFFF){cp=0x10000+((cp-0xD800)<<10)+(chars[++i]-0xDC00);}else if(cp>=0xD800&&cp<=0xDFFF)cp=0xFFFD;
        if(cp<0x80)text.push_back(cp);else if(cp<0x800){text.push_back(0xC0|(cp>>6));text.push_back(0x80|(cp&63));}else if(cp<0x10000){text.push_back(0xE0|(cp>>12));text.push_back(0x80|((cp>>6)&63));text.push_back(0x80|(cp&63));}else{text.push_back(0xF0|(cp>>18));text.push_back(0x80|((cp>>12)&63));text.push_back(0x80|((cp>>6)&63));text.push_back(0x80|(cp&63));}}
        e->ReleaseStringChars(input,chars);int n=-llama_tokenize(llama_model_get_vocab(vocabulary_model),text.data(),text.size(),nullptr,0,false,true);if(n<=0)throw std::runtime_error("Could not count text tokens");return n;
    }catch(const std::exception &error){fail(e,error.what());return 0;}
}
extern "C" JNIEXPORT jstring JNICALL Java_org_localknowledge_library_NativeModels_generate(JNIEnv *e,jclass,jstring path,jstring input,jstring grammar,jint limit) {
    std::lock_guard<std::mutex> lock(guard);llama_context *ctx=nullptr;llama_sampler *sampler=nullptr;
    try {
        load(str(e,path));auto prompt=tokens(str(e,input));if(limit<1||limit>192||prompt.size()+limit+16>1024)throw std::runtime_error("Qwen context budget exceeded");
        auto deadline=Clock::now()+std::chrono::seconds(45);
        auto p=llama_context_default_params();p.n_ctx=1024;p.n_batch=1024;p.n_ubatch=128;p.n_threads=threads();p.n_threads_batch=threads();p.abort_callback=expired;p.abort_callback_data=&deadline;
        ctx=llama_init_from_model(model,p);if(!ctx)throw std::runtime_error("Could not allocate Qwen context");
        auto batch=llama_batch_get_one(prompt.data(),prompt.size());if(llama_decode(ctx,batch)!=0)throw std::runtime_error("Qwen prompt failed");
        sampler=llama_sampler_chain_init(llama_sampler_chain_default_params());
        auto grammar_text=str(e,grammar);
        auto *rule=llama_sampler_init_grammar(llama_model_get_vocab(model),grammar_text.c_str(),"root");
        if(!rule)throw std::runtime_error("Invalid local output grammar");
        llama_sampler_chain_add(sampler,rule);llama_sampler_chain_add(sampler,llama_sampler_init_greedy());
        std::string output;
        for(int i=0;i<limit;i++) {
            if(Clock::now()>deadline)throw std::runtime_error("Qwen time budget exceeded; use source matches or shorten the request");
            auto token=llama_sampler_sample(sampler,ctx,-1);
            if(llama_vocab_is_eog(llama_model_get_vocab(model),token))break;
            char piece[512];int n=llama_token_to_piece(llama_model_get_vocab(model),token,piece,sizeof(piece),0,true);
            if(n<0)throw std::runtime_error("Token piece exceeds output limit");output.append(piece,n);
            auto next=llama_batch_get_one(&token,1);if(llama_decode(ctx,next)!=0)throw std::runtime_error("Qwen generation failed");
        }
        llama_sampler_free(sampler);llama_free(ctx);return e->NewStringUTF(output.c_str());
    }catch(const std::exception &error){if(sampler)llama_sampler_free(sampler);if(ctx)llama_free(ctx);fail(e,error.what());return nullptr;}
}
extern "C" JNIEXPORT void JNICALL Java_org_localknowledge_library_NativeModels_releaseNative(JNIEnv *,jclass){std::lock_guard<std::mutex> lock(guard);if(vocabulary_model)llama_model_free(vocabulary_model);vocabulary_model=nullptr;vocabulary_path.clear();token_cache.clear();clear_embedding();if(model)llama_model_free(model);model=nullptr;loaded.clear();}
