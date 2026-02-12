# Популярные Unikernels

## MirageOS

```ocaml
(* Простое HTTP-сервер на MirageOS (OCaml) *)
open Lwt.Infix

module Main (S: Mirage_stack.V4) = struct
  let start s =
    let port = Key_gen.port () in
    S.listen_tcpv4 s ~port (fun flow ->
      let dst, dst_port = S.TCPV4.dst flow in
      Logs.info (fun f -> f "new tcp connection from %s:%d"
        (Ipaddr.V4.to_string dst) dst_port);
      S.TCPV4.write flow (Cstruct.of_string "Hello from MirageOS!")
      >>= fun _ -> S.TCPV4.close flow
    );
    S.listen s
end
```

**Характеристики:**
- Язык: OCaml
- Размер: ~1MB для простых приложений
- Безопасность: Type-safe, memory-safe
- Использование: DNS серверы, SSL прокси, брандмауэры

## IncludeOS

```cpp
// Простое HTTP-сервер на IncludeOS (C++)
#include <os>
#include <net/inet4>
#include <http>

void Service::start(const std::string&) {
    auto& inet = net::Inet4::stack();
    
    inet.tcp().listen(80, [](auto conn) {
        conn->write("HTTP/1.1 200 OK\r\n"
                   "Content-Type: text/plain\r\n"
                   "Content-Length: 20\r\n\r\n"
                   "Hello from IncludeOS!");
    });
}
```

**Характеристики:**
- Язык: C++
- Размер: ~5MB для простых приложений
- Производительность: Близка к bare metal
- Использование: Edge computing, CDN, IoT

## OSv

**Характеристики:**
- POSIX-compliant
- Поддержка Java, Python, Node.js, Ruby
- Работает на KVM, Xen, VMWare, AWS, GCE
- Оптимизация для JVM

```bash
# Запуск Java приложения на OSv
./scripts/run.py -e "java -jar myapp.jar"

# Размер образа: ~20-50MB для Java приложения
```

## Rumprun

```bash
# Компиляция существующего приложения в unikernel
rumprun-bake hw_generic myapp.bin myapp

# Запуск
rumprun kvm -i myapp.bin

# Поддержка: C, C++, Python, Node.js, Erlang, и др.
```

**Характеристики:**
- POSIX-compliant
- Работает с существующими приложениями
- Поддержка rump kernel (NetBSD drivers)
- Easy migration path
