'use strict';

const TARGET_RE = /(smart[-_]?plug|\/plug\b|wakeup\/devices|get[-_]?status|get[-_]?electric|electric(?:ity)?|outlet)/i;
const SENSITIVE_KEY_RE = /^(authorization|cookie|set-cookie|token|access_token|refresh_token|user-auth|sn|serial|serial_number|mac|mac_addr|userid|user_id|uid|uuid|account|deviceid|device_id|clientid|client_id|client_auth|secret|key)$/i;
const hookedAddresses = new Set();

function redactObject(value, depth) {
  if (depth > 8) return '<max-depth>';
  if (Array.isArray(value)) return value.map((item) => redactObject(item, depth + 1));
  if (value !== null && typeof value === 'object') {
    const out = {};
    Object.keys(value).forEach((key) => {
      out[key] = SENSITIVE_KEY_RE.test(key) ? '<redacted>' : redactObject(value[key], depth + 1);
    });
    return out;
  }
  return value;
}

function sanitizeText(input) {
  let text = String(input || '');
  text = text.replace(/^([^:\r\n]*(?:auth|token|cookie|client[-_]?id|api[-_]?key|secret)[^:\r\n]*)\s*:\s*.*$/gim, '$1: <redacted>');
  text = text.replace(/([?&](?:token|access_token|refresh_token|sn|serial|mac|userid|user_id|uid|uuid|account|deviceid|device_id|clientid|client_id|secret|key)=)[^&#\s]*/gi, '$1<redacted>');
  text = text.replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/gi, '<redacted-uuid>');
  text = text.replace(/([|&;,](?:userid|user_id|uid|uuid|account|sn|serial|mac|deviceid|clientid|client_auth)\s*[:=])[^|&;,\r\n]*/gi, '$1<redacted>');
  text = text.replace(/(\/(?:users|services|switch)\/)[0-9]{6,}(?=\b|\/|\?)/gi, '$1<redacted>');
  try {
    const trimmed = text.trim();
    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
      return JSON.stringify(redactObject(JSON.parse(trimmed), 0));
    }
  } catch (_) {
    // Preserve non-JSON protocol text after applying header/query redaction.
  }
  return text;
}

function emit(kind, value) {
  const safe = sanitizeText(value);
  if (TARGET_RE.test(safe)) console.log(`[${kind}] ${safe.slice(0, 16384)}`);
}

function safeReadUtf8(pointer, length) {
  if (pointer.isNull() || length <= 0 || length > 4 * 1024 * 1024) return null;
  try {
    const bytes = pointer.readByteArray(Math.min(length, 65536));
    if (bytes === null) return null;
    const data = new Uint8Array(bytes);
    let printable = 0;
    const sampleLength = Math.min(data.length, 256);
    for (let i = 0; i < sampleLength; i++) {
      const b = data[i];
      if (b === 9 || b === 10 || b === 13 || (b >= 32 && b <= 126)) printable++;
    }
    if (sampleLength > 0 && printable / sampleLength < 0.72) return null;
    return pointer.readUtf8String(Math.min(length, 65536));
  } catch (_) {
    return null;
  }
}

function hookNativeFunction(module, name, direction) {
  let address = null;
  try {
    address = module.findExportByName(name);
  } catch (_) {
    return;
  }
  if (address === null || hookedAddresses.has(address.toString())) return;
  hookedAddresses.add(address.toString());
  Interceptor.attach(address, {
    onEnter(args) {
      this.buffer = args[1];
      this.requested = args[2].toInt32();
      if (direction === 'write') {
        const value = safeReadUtf8(this.buffer, this.requested);
        if (value !== null) emit(`native ${module.name}!${name}`, value);
      }
    },
    onLeave(retval) {
      if (direction !== 'read') return;
      const actual = retval.toInt32();
      const value = safeReadUtf8(this.buffer, actual);
      if (value !== null) emit(`native ${module.name}!${name}`, value);
    }
  });
  console.log(`[+] hooked ${module.name}!${name} at ${address}`);
}

function scanNativeTls() {
  Process.enumerateModules().forEach((module) => {
    hookNativeFunction(module, 'SSL_write', 'write');
    hookNativeFunction(module, 'SSL_read', 'read');
  });
}

function hookDlopen() {
  ['android_dlopen_ext', 'dlopen'].forEach((name) => {
    let address = null;
    try {
      address = Module.findGlobalExportByName(name);
    } catch (_) {
      return;
    }
    if (address === null || hookedAddresses.has(address.toString())) return;
    hookedAddresses.add(address.toString());
    Interceptor.attach(address, {
      onLeave() {
        setTimeout(scanNativeTls, 100);
      }
    });
  });
}

function hookJavaNetwork() {
  Java.perform(() => {
    try {
      const URL = Java.use('java.net.URL');
      URL.$init.overload('java.lang.String').implementation = function (value) {
        emit('java URL', value);
        return this.$init(value);
      };
      console.log('[+] hooked java.net.URL(String)');
    } catch (error) {
      console.log(`[-] java.net.URL hook unavailable: ${error}`);
    }

    try {
      const Interceptor = Java.use('okhttp3.Interceptor');
      const TraceInterceptor = Java.registerClass({
        name: 'com.oray.sunlogin.FridaReadOnlyTraceInterceptor',
        implements: [Interceptor],
        methods: {
          intercept(chain) {
            const request = chain.request();
            const url = request.url().toString();
            if (TARGET_RE.test(url)) {
              const headerNames = request.headers().names().toString();
              emit('okhttp request', `${request.method()} ${url} header-names=${headerNames}`);
            }
            const response = chain.proceed(request);
            if (TARGET_RE.test(url)) {
              try {
                const body = response.peekBody(65536).string();
                emit('okhttp response', `${request.method()} ${url}\n${body}`);
              } catch (error) {
                console.log(`[-] response preview failed for ${sanitizeText(url)}: ${error}`);
              }
            }
            return response;
          }
        }
      });
      const Builder = Java.use('okhttp3.Request$Builder');
      const build = Builder.build.overload();
      build.implementation = function () {
        const request = build.call(this);
        const url = request.url().toString();
        if (TARGET_RE.test(url)) {
          emit('okhttp request', `${request.method()} ${url} header-names=${request.headers().names().toString()}`);
        }
        return request;
      };
      console.log('[+] hooked okhttp3.Request$Builder.build()');

      const ClientBuilder = Java.use('okhttp3.OkHttpClient$Builder');
      const clientBuild = ClientBuilder.build.overload();
      clientBuild.implementation = function () {
        try {
          this.addNetworkInterceptor(TraceInterceptor.$new());
        } catch (error) {
          console.log(`[-] unable to add trace interceptor: ${error}`);
        }
        return clientBuild.call(this);
      };
      console.log('[+] installed passive OkHttp response interceptor');
    } catch (error) {
      console.log(`[-] OkHttp request hook unavailable: ${error}`);
    }

    try {
      const ResponseBody = Java.use('okhttp3.ResponseBody');
      const stringMethod = ResponseBody.string.overload();
      stringMethod.implementation = function () {
        const value = stringMethod.call(this);
        emit('okhttp response', value);
        return value;
      };
      console.log('[+] hooked okhttp3.ResponseBody.string()');
    } catch (error) {
      console.log(`[-] OkHttp response hook unavailable: ${error}`);
    }
  });
}

console.log('[*] Sunlogin passive network trace loaded (no request mutation)');
hookDlopen();
scanNativeTls();
if (Java.available) hookJavaNetwork();
