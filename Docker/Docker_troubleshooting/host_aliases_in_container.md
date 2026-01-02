# Использование своих alias'ов в контейнере

**Проблема:** Ваши привычные alias'ы и функции из `~/.bashrc` не работают внутри контейнера.

**Решение:** Смонтировать `bashrc` с хоста в контейнер при запуске.

```sh
docker run -it \
  -v ~/.bashrc:/root/.bashrc \
  --env BASH_ENV=/root/.bashrc \
  ubuntu bash
```
