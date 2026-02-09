# HTTPie: Современный HTTP-клиент

## Ключевые особенности и синтаксис

* **Интуитивный синтаксис:** Методы (`GET`, `POST`) указываются как подкоманды. Параметры запроса добавляются в виде пар `ключ==значение` для URL-параметров и `ключ=значение` для тела запроса. По умолчанию `HTTPie` отправляет данные тела запроса в формате JSON.

    ```bash
    # GET-запрос с URL-параметром
    # Эквивалентно curl "http://httpbin.org/get?name=John"
    http GET httpbin.org/get name==John

    # POST-запрос с JSON-телом (по умолчанию)
    # Эквивалентно curl -X POST -H "Content-Type: application/json" -d '{"name":"John"}' http://httpbin.org/post
    http POST httpbin.org/post name=John
    ```

    Для явного указания формата формы или multipart можно использовать опции `--form` или `--multipart`.

* **Сессии:** `HTTPie` может автоматически сохранять и переиспользовать cookies, заголовки `Authorization` и другие данные между запросами в рамках одной сессии. Сессии могут быть именованными и сохраняться в домашней директории пользователя.

    ```bash
    # Создаем сессию с именем 'my_session' и логинимся
    http --session=my_session POST http://example.com/login user=test pass=123
    # Последующие запросы в этой сессии автоматически используют полученные cookies
    http --session=my_session GET http://example.com/profile
    ```

* **Аутентификация:** Встроенная поддержка различных схем аутентификации, включая Basic, Digest и Bearer.

    ```bash
    # Basic аутентификация
    http -a user:password http://example.com/protected

    # Bearer токен
    http -A bearer -a YOUR_TOKEN_HERE http://example.com/api/resource
    ```

* **Офлайн-режим:** Позволяет посмотреть, как будет выглядеть запрос, не отправляя его на сервер.

    ```bash
    # -o, --offline: не отправлять запрос, только показать его
    http --offline POST httpbin.org/post name=John
    ```
