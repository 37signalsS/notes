# Инструкции Dockerfile: Выполнение Команд При Сборке

### Выполнение команд при сборке

#### `RUN`

Определяет команду, которая будет выполнена во время сборки образа, создавая новый слой.

- **Надежные скрипты с `set -ex` при написании многострочных `RUN` команд**

  ```dockerfile
  RUN set -ex && 
      apt-get update && 
      apt-get install -y curl && 
      rm -rf /var/lib/apt/lists/*
  ```

  - `set -e`: **Exit Immediately.** Если какая-либо команда завершится с ошибкой (ненулевым кодом выхода), выполнение всей `RUN` инструкции немедленно прекратится. Без этого флага Docker продолжит выполнение следующих команд, как будто ничего не произошло, и сборка может успешно завершиться, скрыв проблему.
  - `set -x`: **Print Commands.** Перед выполнением каждой команды она будет напечатана в лог сборки. Это помогает четко видеть, какая именно команда выполняется в данный момент и какие у нее аргументы, что неоценимо при отладке.

- **Кэширование зависимостей:**
   `--mount=type=cache` позволяет монтировать кэш в процессе выполнения `RUN`. Это ускоряет повторные сборки, так как зависимости будут взяты из кэша, хранящегося на хосте. Кэш не попадает в финальный образ, но доступен для повторного использования.

   > Подробнее о кэшировании и оптимизации сборки см. **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)**

  ```dockerfile
  RUN --mount=type=cache,target=/root/.cache/pip 
      pip install -r requirements.txt
  ```

- **Bind mounts при сборке:**
  `--mount=type=bind` позволяет монтировать директорию или файл с хостовой системы в контейнер во время выполнения команды `RUN`. В отличие от `COPY`, данные не копируются в образ, а временно подключаются с хоста для процесса сборки.

  ```dockerfile
  RUN --mount=type=bind,source=./src,target=/app/src 
      go build -o app ./src
  ```

- **Работа с секретами:**
  `--mount=type=secret` временно монтирует секрет с хоста и не хранит его в финальном образе.

  ```dockerfile
  RUN --mount=type=secret,id=ssh,target=/root/.ssh/id_rsa 
      git clone git@github.com:user/repo.git .
      
  RUN --mount=type=secret,id=api_key,target=/run/secrets/api_key 
      export API_KEY=$(cat /run/secrets/api_key) && 
      pip install --extra-index-url "$API_KEY"@private-repo.com/packages some-package
  ```
