# Debian Repositories (`sources.list`)

Файл `/etc/apt/sources.list` и файлы в директории `/etc/apt/sources.list.d/` определяют, откуда система управления пакетами APT (Advanced Package Tool) будет загружать пакеты.

Каждая строка в `sources.list` имеет следующую структуру:

```
<type> <url> <distribution> <component_1> <component_2> ...
```

-   **`type`**: Тип архива.
    -   `deb`: бинарные пакеты (скомпилированные приложения).
    -   `deb-src`: исходные коды пакетов.
-   **`url`**: Базовый URL репозитория.
-   **`distribution`**: Имя выпуска (кодовое имя) или класс выпуска (stable, testing, unstable). Например, `buster`, `bookworm`, `stable`.
-   **`component`**: Компоненты репозитория.
    -   `main`: Основные, полностью свободные пакеты.
    -   `contrib`: Пакеты, которые сами по себе свободны, но зависят от несвободных пакетов.
    -   `non-free`: Пакеты, которые не соответствуют Debian Free Software Guidelines.
    -   `non-free-firmware`: Несвободные прошивки, необходимые для работы некоторого оборудования. (появился в Debian 12).

---

## Сторонние репозитории

### Пример: Установка Node.js на Debian 13 "Trixie"

1.  **Установка зависимостей и GPG-ключа(необходимо чтобы APT доверял репозиторию, необходимо импортировать его публичный ключ. Без этого `apt update` будет выдавать ошибку):**

    ```bash
    sudo apt update
    sudo apt install -y ca-certificates curl gnupg
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    ```

2.  **Добавление репозитория NodeSource:**

    Создается файл `/etc/apt/sources.list.d/nodesource.list` со следующим содержимым:

    ```bash
    NODE_MAJOR=24
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
    ```
    *Примечание: `nodistro` используется для совместимости с различными дистрибутивами.*
    *Примечание 2: `Node.js 24` является "Current" версией. Для производственных сред рекомендуется использовать LTS (Long-Term Support) версии, например, `22.x`.*

3.  **Установка Node.js:**

    ```bash
    sudo apt update
    sudo apt install nodejs -y
    ```
