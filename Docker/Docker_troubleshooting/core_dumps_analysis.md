# Сбор и анализ Core Dumps в Docker

### 1. Настройка хоста

Чтобы система сохраняла дампы, необходимо задать шаблон `core_pattern`.

```bash
# Указываем, куда и в каком формате сохранять core dump
echo '/tmp/core.%e.%p' | sudo tee /proc/sys/kernel/core_pattern
```

*   `%e` - имя исполняемого файла.
*   `%p` - PID процесса.

**Важно:** Путь `/tmp/` должен существовать на хосте и быть доступным для записи.

### 2. Пример приложения для отладки

Простая C++ программа, которая вызывает `std::abort()` для генерации `core dump`.

**main.cpp:**
```cpp
#include <cstdlib>

void foo() {
    std::abort();
}

int main() {
    foo();
}
```

### 3. Dockerfile для сборки

Образ включает `build-essential` для компиляции и `gdb` для анализа дампа.

```dockerfile
FROM ubuntu:22.04

RUN apt update \
    && apt -y install build-essential gdb \
    && rm -rf /var/lib/apt/lists/*

COPY ./main.cpp /src/
WORKDIR /src/

RUN g++ main.cpp -o app
CMD ["/src/app"]
```

### 4. Запуск контейнера

При запуске необходимо передать несколько ключевых флагов.

```bash
docker run \
    --init \
    --ulimit core=-1 \
    --mount type=bind,source=/tmp/,target=/tmp/ \
    my-app:latest
```

*   `--init`: Использует `tini` как init-процесс, что обеспечивает корректную обработку сигналов.
*   `--ulimit core=-1`: Снимает ограничение на размер `core dump` файла (по умолчанию 0), разрешая его создание.
*   `--mount type=bind,source=/tmp/,target=/tmp/`: Монтирует директорию `/tmp` с хоста в контейнер, чтобы сгенерированный дамп сохранился на хосте. Путь `source` должен совпадать с `core_pattern`.

После падения приложения дамп появится на хосте:
```bash
$ ls /tmp/core*
/tmp/core.app.5
```

### 5. Анализ дампа с помощью GDB

Анализировать `core dump` следует в окружении, идентичном тому, где он был создан. Для этого запустим новый контейнер из того же образа.

```bash
docker run -it --rm \
    --mount type=bind,source=/tmp/,target=/tmp/ \
    --mount type=bind,source=$(pwd),target=/src/ \
    my-app:latest bash
```
*   Первый `--mount` предоставляет доступ к файлу дампа.
*   Второй `--mount` монтирует исходный код для более детального анализа в `gdb`.

Внутри контейнера запускаем `gdb`:

```bash
# gdb <путь_к_исполняемому_файлу> <путь_к_дампу>
gdb /src/app /tmp/core.app.5
```

Основная команда для анализа — `bt` (backtrace), которая покажет стек вызовов в момент аварии.

```gdb
(gdb) bt
#0  __GI_raise (sig=sig@entry=6) at ../sysdeps/unix/sysv/linux/raise.c:50
#1  0x00007f3e8b422859 in __GI_abort () at abort.c:79
#2  0x000055a9b9a6719b in foo() ()
#3  0x000055a9b9a671ab in main ()
```
Из вывода видно, что падение произошло из-за вызова `abort()` в функции `foo()`.

### Использование с `docker-compose`

Все флаги можно перенести в `docker-compose.yml`, логика останется той же.

```yaml
version: '3.8'
services:
  app:
    build: .
    init: true
    ulimits:
      core: -1 # Разрешает создание core dump
    volumes:
      - /tmp:/tmp # Монтирует директорию для дампов
      - .:/src # Монтирует исходный код для отладки
```

Этот подход позволяет быстро локализовать аварии, воспроизвести проблему и детально проанализировать стек вызовов.
