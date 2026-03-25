# Популярные Unikernel-проекты

## Определения

В этом документе представлены примеры популярных фреймворков и реализаций **unikernels** с краткими характеристиками и фрагментами кода.

Для понимания базовых концепций unikernels ознакомьтесь с [общим обзором](./unikernel_overview.md).

## Основные концепции

### Критерии выбора unikernel-фреймворка

При выборе фреймворка для разработки unikernel учитывайте:

* **Язык разработки:** OCaml (MirageOS), C++ (IncludeOS), или поддержка существующего кода (OSv, Rumprun)
* **Совместимость:** Требуется ли POSIX-совместимость для портирования существующих приложений
* **Размер образа:** От 1-2 МБ (MirageOS) до 10+ МБ (IncludeOS, OSv)
* **Экосистема:** Зрелость фреймворка и доступность библиотек
* **Целевая платформа:** KVM, Xen, AWS, GCE, VMware

### Классификация популярных проектов

| Проект | Язык | Совместимость | Размер | Зрелость |
| :--- | :--- | :--- | :--- | :--- |
| **MirageOS** | OCaml | Clean-slate | ~1-2 МБ | Высокая |
| **IncludeOS** | C++ | Минимальная | ~5-10 МБ | Средняя |
| **OSv** | C++ | POSIX | ~10-20 МБ | Высокая |
| **Rumprun** | C | POSIX | ~5-15 МБ | Средняя |

## Практические сценарии

### 1. MirageOS

* **Описание:** "Чистый" unikernel-фреймворк, написанный с нуля на **OCaml**. Делает упор на типобезопасность и надежность. Весь стек, включая драйверы, реализован на OCaml.
* **Характеристики:**
  * **Язык:** OCaml.
  * **Размер:** ~1-2 МБ для простого HTTP-сервера.
  * **Безопасность:** Высокая, благодаря типобезопасности и отсутствию C-кода в стеке.
  * **Применение:** DNS-серверы, TLS-прокси, внутренние сервисы Docker.

* **Пример: Простой HTTP-сервер**

    ```ocaml
    (* hello.ml *)
    open Lwt.Infix

    module Main (S: Mirage_stack.V4) = struct
      let start s =
        let port = 8080 in
        S.listen_tcpv4 s ~port (fun flow ->
          let body = "Hello from MirageOS!" in
          let headers = "Content-Type: text/plain\r\nContent-Length: " ^ (string_of_int (String.length body)) ^ "\r\n\r\n" in
          let response = "HTTP/1.1 200 OK\r\n" ^ headers ^ body in
          S.TCPV4.write flow (Cstruct.of_string response)
          >>= fun _ -> S.TCPV4.close flow
        );
        S.listen s
    end
    ```

### 2. IncludeOS

* **Описание:** Unikernel-фреймворк для запуска сервисов на **C++**. Предоставляет минимальный набор библиотек для работы с сетью, файловой системой и т.д.
* **Характеристики:**
  * **Язык:** C++.
  * **Размер:** ~5-10 МБ.
  * **Производительность:** Очень высокая, близкая к bare-metal.
  * **Применение:** Edge computing, CDN, IoT, высокопроизводительные вычисления.

* **Пример: Простой HTTP-сервер**

    ```cpp
    // service.cpp
    #include <os>
    #include <net/inet4>

    void Service::start() {
      auto& inet = net::Inet4::stack();
      inet.tcp().listen(8080, [](auto conn) {
        conn->write("HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nHello from IncludeOS!");
        conn->close();
      });
    }
    ```

### 3. OSv

* **Описание:** Проект, нацеленный на запуск существующих Linux-приложений, особенно написанных для **JVM** (Java, Scala, Kotlin) и других управляемых сред выполнения (Python, Node.js).
* **Характеристики:**
  * **Совместимость:** Высокая степень POSIX-совместимости.
  * **Языки:** Java, Python, Node.js, Ruby, Go, C/C++.
  * **Платформы:** KVM, Xen, VMware, AWS, GCE.
  * **Применение:** Миграция существующих Java-приложений в облако.

* **Пример: Запуск Java-приложения**

    ```bash
    # Сборка образа с вашим приложением
    ./scripts/build image=java-app
    # Запуск
    ./scripts/run.py -e "java -jar /app/myapp.jar"
    ```

### 4. Rumprun

* **Описание:** Использует технологию "rump kernel" для запуска существующих POSIX-приложений как unikernels. Позволяет использовать драйверы из ядра NetBSD вне основной ОС.
* **Характеристики:**
  * **Совместимость:** Хорошая, подходит для портирования.
  * **Простота:** Относительно простой путь миграции для существующих приложений.
  * **Применение:** Быстрое превращение существующих утилит и сервисов в unikernels.

* **Пример: "Запекание" и запуск приложения**

    ```bash
    # 1. "Запечь" бинарный файл в unikernel
    rumprun-bake hw_generic my_unikernel.bin ./myapp

    # 2. Запустить на гипервизоре KVM
    rumprun kvm -i my_unikernel.bin
    ```

## Дополнительная информация

### Ресурсы проектов

* [MirageOS](https://mirage.io/) — официальный сайт, документация и примеры
* [IncludeOS](https://www.includeos.org/) — репозиторий и документация
* [OSv](https://osv.io/) — проект на GitHub
* [Rumprun](https://github.com/rumpkernel/rumprun) — репозиторий на GitHub

### Связанные документы

* [Обзор Unikernels](./unikernel_overview.md) — базовые концепции и архитектура
* [Преимущества и ограничения](./unikernel_advantages_disadvantages.md) — сравнение с традиционными подходами
* [Сценарии использования](./use_cases.md) — практические кейсы применения
* [Инструменты и будущее](./tools_future.md) — UniK, OPS, Firecracker, Wasm
