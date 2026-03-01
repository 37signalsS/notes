# Docker Swarm: Шпаргалка по CLI

## Управление кластером (Swarm)

* **Инициализировать Swarm:**
    Превращает текущий хост в менеджер Swarm.

    ```sh
    docker swarm init --advertise-addr <MANAGER-IP>
    ```

* **Присоединить узел к Swarm:**
    Выполняется на узле, который нужно добавить в кластер. Токен можно получить командой `docker swarm join-token worker` (или `manager`) на менеджере.

    ```sh
    docker swarm join --token <TOKEN> <MANAGER-IP>:<PORT>
    ```

* **Вывести узел из Swarm:**

    ```sh
    # Для рабочего узла
    docker swarm leave
    
    # Для менеджера (требует --force)
    docker swarm leave --force
    ```

### Управление узлами (Node)

* **Список всех узлов в кластере:**

    ```sh
    docker node ls
    ```

* **Изменение роли узла:**

    ```sh
    # Повысить рабочего до менеджера
    docker node promote <NODE-ID>
    
    # Понизить менеджера до рабочего
    docker node demote <NODE-ID>
    ```

* **Удаление узла из кластера:**
    Выполняется с менеджера.

    ```sh
    docker node rm <NODE-ID>
    ```

### Управление сервисами (Service)

* **Создание сервиса:**

    ```sh
    docker service create --name my-web --publish 80:80 --replicas 3 nginx:1.26.3
    ```

* **Список всех сервисов:**

    ```sh
    docker service ls
    ```

* **Масштабирование сервиса:**
    Изменяет количество реплик для сервиса.

    ```sh
    docker service scale my-web=5
    ```

* **Просмотр задач (контейнеров) сервиса:**
    Показывает, на каких узлах запущены реплики и их статус.

    ```sh
    docker service ps my-web
    ```

* **Обновление сервиса (Rolling Update):**
    Например, для смены версии образа. Swarm выполнит обновление "на лету".

    ```sh
    docker service update --image nginx:1.26.4 my-web
    ```

* **Откат обновления:**
    Возвращает сервис к предыдущей конфигурации.

    ```sh
    docker service rollback my-web
    ```

* **Удаление сервиса:**

    ```sh
    docker service rm my-web
    ```
