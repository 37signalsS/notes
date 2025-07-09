# **Полезные команды и решение проблем**

---

### **Мониторинг ресурсов**

- Инфа о использовании ресурсов всех запущенных контейнеров
```sh
docker stats
```

- Инфа о использовании ресурсов запущенного контейнеров
```sh
docker stats <container_id>
```

- Показывает однократный снимок статистики по ресурсам (CPU, память, сеть) всех контейнеров.
```sh
docker stats --no-stream
```

- Cколько пространства на диске занимают образы, контейнеры, сети и тома в Docker
```sh
docker system df
```

---

### **Управление контейнерами**

- Узнать имя-индентификатор контейнера и информацию по нему
```sh
docker ps -a
```

- Остановить контейнер
```sh
docker stop <container_id>
```

- Поднять контейнер
```sh
docker start <container_id>
```

- Остановить процессы в контейнере без его остановки (полезно для отладки).
```sh
docker pause <container_name>
```

- Запустить контейнер nginx с определенной версией 1.14-alpine и задать ему имя
```sh
docker run --name webapp -d nginx:1.14-alpine
```

- Запуск контейнера с пробросом портов, присвонием тега blue(для версионирования) и использованием переменной среды(в которую можно засунуть пароли и т.д.) APP_COLOR=blue, пробрасывается 38282 на хосте на 8080 в контейнере
```sh
docker run --name simple-webapp-blue -d -e APP_COLOR=blue -p 38282:8080 kodekloud/simple-webapp:blue
```

- Создать контейнер и связать его с другим контейнером
```sh
docker run --name clickcounter-container -d -p 8085:5000 --link redis-container:redis kodekloud/click-counter
```
*> **Примечание:** Флаг `--link` является устаревшим. Для связи контейнеров рекомендуется использовать `docker network`.*

- **Создание и использование сетей**
```sh
# Создать новую сеть
docker network create my-network

# Запустить контейнеры в одной сети
docker run --name redis-container --network my-network -d redis
docker run --name clickcounter-container --network my-network -d -p 8085:5000 kodekloud/click-counter
```

- Сохранить базу данных по поределенному адресу
```sh
docker run --name mysql-db -v /opt/data:/var/lib/mysql -d mysql
```

- Запустить контейнер с монтированием локальной директории /data в контейнер по пути /app
```sh
docker run -v /data:/app <image_name>
```

- Запустить контейнер, чтобы он автоматически удалялся после завершения работы
```sh
docker run --rm <image_name>
```

- Ограничить использование памяти, выделенных ядер, процесоов и объема swap контейнером
```sh
docker run --memory 512m --cpus=1.5 --pids-limit=50 --memory-swap=1 <image_name>
```

- Динамическое изменение ресурсов контейнера
```sh
docker update --memory 1G --cpus 2 my_container
```

- Послучить доступ к командной строке контейнера
```sh
docker exec -it <container_id> /bin/bash
```

---

### **Работа с образами (Images)**

- Удалить images
```sh
docker rmi <name>
```

- Скачать images/образ
```sh
docker pull <image_name>
```

- Создание контейнера на основании Dockerfile с именем webapp-color из текущей директории(перед точкой можно добавить флаг -f и имя докер файла для сборки)
```sh
docker build -t webapp-color:0.1 .
```

- Сохранить работающий контейнер в виде нового образа с именем
```sh
docker commit <container_id> my_snapshot
```

- Объединить все слои в один, но отключит использование кэша при повторной сборке.
```sh
docker build --squash -t my-caddy .
```

---

### **Логирование**

- Смотрим логи
```sh
docker logs --tail 30 <container_id>
```

- Смотреть логи в реальном времени
```sh
docker logs -f <container_name>
```

---

### **Сеть (Networking)**

- Узнать какие порты открыты на контейнере
```sh
docker port <container_name>
```

- Список всех докер сетей
```sh
docker network ls
```

- Определить все настройки контейнера и в том числе принадлежность к определенной сети
```sh
docker inspect alpine-1
```

- Запустить контеней привязав его к определенной сети
```sh
docker run --name alpine-2 --network bridge -d alpine
```

- Созданить новую сеть испльзуя драйвер bridge, подсеть и шлюз
```sh
docker network create --driver bridge --subnet=182.18.0.0/24 --gateway=182.18.0.1 wp-mysql-network
```

---

### **Очистка**

- Удалить все остановленные контейнеры на хосте
```sh
docker container prune
```

- Очистить все неиспользуемые данные (остановленные контейнеры, образы без тега, сети и тома)
```sh
docker system prune
```

---

### **Копирование файлов**

- Копирование файла или папки из хоста в работающий контейнер
```sh
docker cp /path/on/host <container_name>:/path/in/container
```

---

### **Решение проблем с PostgreSQL**

- Сброс журнала транзакций (WAL) в PostgreSQL
```sh
gosu postgres pg_resetwal /var/lib/postgresql/data
```
*`gosu` — это утилита, используемая для выполнения команд с правами другого пользователя. В данном случае команда gosu используется для выполнения команды от имени пользователя postgres.*
*`pg_resetwal` — это инструмент, предназначенный для сброса журналов транзакций (WAL, Write-Ahead Logs) в PostgreSQL.*