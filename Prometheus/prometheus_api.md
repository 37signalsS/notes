# Prometheus HTTP API

Prometheus предоставляет HTTP API (текущая версия v1) для выполнения запросов и получения данных. API доступен по пути `/api/v1/`.

## Общие сведения для запросов API

-   **Формат ответа:** JSON.
-   **Коды ответа:**
    -   `2xx`: Успешный запрос.
    -   `400`: Неверные или отсутствующие параметры.
    -   `422`: Запрос не может быть выполнен.
    -   `503`: Таймаут выполнения запроса.
-   **Метки времени:** Могут быть переданы в формате [RFC3339](https://www.ietf.org/rfc/rfc3339.txt) или как Unix timestamp.
-   **Методы запроса:** `GET` или `POST`. При `GET` параметры добавляются к URL, при `POST` — передаются в теле запроса.

## Запросы мгновенного вектора

-   **Endpoint:** `/api/v1/query`
-   **Method:** `GET` | `POST`
-   **Параметры:**
    -   `query`: строка запроса PromQL.
    -   `time`: временная метка, за которую надо выбрать данные. Если не задан, берется текущее время.
    -   `timeout`: максимальное время выполнения. Необязательный.

**Пример запроса (GET):**
*Запрос `up`, время: 19.11.2019 09:10.51. Перед выполнением запроса измените время на текущее. Время указывается в UTC.*
```bash
curl 'http://localhost:9090/api/v1/query?query=up&time=2019-11-19T09:10:51.781Z'
```

**Пример ответа:**
```json
{ 
   "status":"success",
   "data":{ 
	  "resultType":"vector",
	  "result":[ 
	     { 
	        "metric":{ 
	           "__name__":"up",
	           "instance":"192.168.0.12:9100",
	           "job":"openstack"
	        },
	        "value":[ 
	           1574154651.781,
	           "1"
	        ]
	     }
        // ... другие метрики
	  ]
   }
}
```

**Пример запроса (POST):**
```bash
curl -XPOST -H 'Content-Type: application/x-www-form-urlencoded' -d "query=up" -d "time=2019-11-19T09:10:51.781Z" http://localhost:9090/api/v1/query
```
> **NB!** `Content-Type` используется: `application/x-www-form-urlencoded`.

## Запрос вектора за период времени

-   **Endpoint:** `/api/v1/query_range`
-   **Method:** `GET` | `POST`
-   **Параметры:**
    -   `query`: строка запроса PromQL.
    -   `start`: временная метка начала вектора.
    -   `end`: временная метка окончания вектора.
    -   `step`: шаг выборки данных (например, `5s` или число float в секундах).
    -   `timeout`: максимальное время выполнения. Необязательный.

**Пример:** *Запрос `up` за период с 19.11.2019 10:00.50 по 19.11.2019 10:15.50, с шагом в 30 секунд.*
```bash
curl 'http://localhost:9090/api/v1/query_range?query=up&start=2019-11-19T09:10:51.781Z&end=2019-11-19T09:15:51.781Z&step=30s'
```

**Пример ответа:**
```json
{ 
   "status":"success",
   "data":{ 
      "resultType":"matrix",
      "result":[ 
         { 
            "metric":{ 
               "__name__":"up",
               "instance":"192.168.0.12:9100",
               "job":"openstack"
            },
            "values":[ 
               [1574154651.781, "1"],
               [1574154681.781, "1"]
               // ... другие значения
            ]
         }
      ]
   }
}
```

## Поиск временных рядов на основании labels

-   **Endpoint:** `/api/v1/series`
-   **Method:** `GET` | `POST`
-   **Параметры:**
    -   `match[]`: задает список меток для поиска. Необходимо задать хотя бы одно условие.
    -   `start`: временная метка начала вектора.
    -   `end`: временная метка окончания вектора.

**Пример:** *Получить данные по всем временным рядам, которые имеют имя `node_disk_write_time_seconds_total` и label `device` со значением `sda`.*
```bash
curl -XPOST -H 'Content-Type: application/x-www-form-urlencoded' -d 'match[]=node_disk_write_time_seconds_total{device="sda"}' http://localhost:9090/api/v1/series
```

**Пример ответа:**
```json
{ 
   "status":"success",
   "data":[ 
      { 
         "__name__":"node_disk_write_time_seconds_total",
         "device":"sda",
         "instance":"192.168.0.12:9100",
         "job":"node_exporter"
      }
      // ... другие ряды
   ]
}
```

## Получение списка меток

-   **Endpoint:** `/api/v1/labels`
-   **Method:** `GET` | `POST`

Данный запрос позволяет получить список всех labels.
```bash
curl 'http://localhost:9090/api/v1/labels'
```

## Запрос значений для label

-   **Endpoint:** `/api/v1/label/<label_name>/values`
-   **Method:** `GET`

Синтаксис запроса: `/api/v1/label/<label_name>/values`, где `<label_name>` — имя label.

**Пример:**
```bash
curl 'http://localhost:9090/api/v1/label/instance/values'
```

## API для получения конфигурации

### Конфигурация сервера
-   **Endpoint:** `/api/v1/status/config`
-   **Method:** `GET`
-   **Описание:** Возвращает текущую конфигурацию сервера в YAML формате.
```bash
curl 'http://localhost:9090/api/v1/status/config'
```

### Список ключей запуска
-   **Endpoint:** `/api/v1/status/flags`
-   **Method:** `GET`
-   **Описание:** Возвращает список ключей и их значений, с которыми запущен сервер.
```bash
curl 'http://localhost:9090/api/v1/status/flags'
```

### Список targets
-   **Endpoint:** `/api/v1/targets`
-   **Method:** `GET`
-   **Описание:** Возвращает информацию о всех targets.
```bash
curl 'http://localhost:9090/api/v1/targets'
```

## Rules и Alerts API

### Alertmanagers
-   **Endpoint:** `/api/v1/alertmanagers`
-   **Method:** `GET`
-   **Описание:** Возвращает список всех настроенных alertmanagers и их статус.
```bash
curl 'http://localhost:9090/api/v1/alertmanagers'
```

### Alerts
-   **Endpoint:** `/api/v1/alerts`
-   **Method:** `GET`
-   **Описание:** Возвращает список активных алертов.
```bash
curl http://localhost:9090/api/v1/alerts
```

### Rules
-   **Endpoint:** `/api/v1/rules`
-   **Method:** `GET`
-   **Описание:** Возвращает список всех правил: как record rules, так и alert rules.
```bash
curl http://localhost:9090/api/v1/rules
```