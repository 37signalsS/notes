## Установка Termux и необходимых пакетов

1. **Установите Termux**:
    Скачайте и установите последнюю версию Termux из [F-Droid](https://f-droid.org/packages/com.termux/). Запуск из Google Play не рекомендуется из-за устаревшей версии.

2. **Обновите репозитории**:
    Откройте Termux и выполните команду для выбора актуальных зеркал.

    ```sh
    termux-change-repo
    ```

    Выберите все репозитории (`All repositories`) и затем `Mirrors by Albatross`.

3. **Установите пакеты**:
    Установим Git для работы с репозиторием, Cronie для запуска по расписанию и Termux Services для управления фоновыми службами.

    ```sh
    pkg update && pkg upgrade -y
    pkg install git cronie termux-services -y
    ```

## Настройка доступа и Git

1. **Доступ к хранилищу**:
    Предоставьте Termux доступ к файлам на устройстве.

    ```sh
    termux-setup-storage
    ```

    Подтвердите разрешение во всплывающем окне Android. Это создаст символическую ссылку `~/storage/shared` на внутреннее хранилище.

2. **Настройка Git**:
    Укажите ваше имя и email для коммитов.

    ```sh
    git config --global user.name "Your Name"
    git config --global user.email "your.email@example.com"
    ```

3. **Кеширование учетных данных (опционально, но удобно)**:
    Эта команда сохранит ваш Personal Access Token (PAT) в текстовом файле, чтобы не вводить его каждый раз.

    ```sh
    git config --global credential.helper store
    ```

    > **Внимание**: Ваш токен будет храниться в открытом виде в файле `~/.git-credentials`. Это небезопасно, если ваше устройство попадет в чужие руки. Альтернатива — настройка SSH-ключей.

## Клонирование репозитория

1. **Перейдите в общую папку**:

    ```sh
    cd ~/storage/shared
    ```

2. **Клонируйте репозиторий**:
    Используйте URL с вашим Personal Access Token (PAT).

    ```sh
    # Замените <TOKEN> и <USER>/<REPO>.git
    git clone https://<PERSONAL_ACCESS_TOKEN>@github.com/<USER>/<REPO>.git my-notes
    ```

    Например: `git clone https://ghp_..._token@github.com/37signalsS/my-notes.git my-notes`

3. **Добавьте репозиторий в исключения безопасности Git**:
    Из-за особенностей файловой системы Android, Git может считать директорию небезопасной. Исправим это:

    ```sh
    # Путь должен быть абсолютным. /storage/emulated/0/ — это стандартный путь к внутреннему хранилищу.
    git config --global --add safe.directory /storage/emulated/0/my-notes
    ```
