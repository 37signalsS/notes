# **Образы Docker (Images)**

---

### **None-образы**

Эти образы обычно появляются в двух ситуациях:

- После сборки нового образа с тем же именем и тегом
- Когда вы пересобираете образ с уже существующим именем (my-image:latest), старый образ становится `<none>`, потому что Docker сохраняет его слои, но он больше не связан с актуальным тегом.

**Промежуточные слои сборки (<none>, но с ID)**

При сборке Docker-образа создаются промежуточные слои. Они не имеют имени, но могут оставаться в системе, если:

- Сборка была прервана.
- Образ был удалён, но слои остались (из-за зависимостей других образов).

---

### **Поиск и удаление образов**

- **Как найти dangling образы?**
```sh
docker images -f "dangling=true"
```

```sh
docker images | grep "<none>"
```

- **Как удалить dangling(висящие) образы?**
```sh
docker image prune
```

- **Удалить все неиспользуемые образы (включая неиспользуемые слои):**
```sh
docker image prune -a
```

---

### **Реверс-инжиниринг образов**

Если вы потеряли `Dockerfile` запущенного контейнера или хотите понять, как был собран существующий образ, есть несколько утилит, которые могут помочь восстановить его из слоёв.

**Восстановление Dockerfile из образа**

Эти утилиты анализируют слои образа и генерируют `Dockerfile`, который мог бы его создать. Они запускаются как Docker-контейнеры и требуют доступа к Docker-сокету.

- **[dduvnjak/dockerfile-from-image](https://github.com/dduvnjak/dockerfile-from-image)** (написан на Ruby)
  ```sh
  sudo docker run -v /var/run/docker.sock:/var/run/docker.sock --rm dduvnjak/dockerfile-from-image <IMAGE_ID>
  ```

- **[laniksj/dfimage](https://github.com/LanikSJ/dfimage)** (написан на Python)
  ```sh
  sudo docker run -v /var/run/docker.sock:/var/run/docker.sock --rm laniksj/dfimage <IMAGE_ID>
  ```

- **[mrhavens/dedockify](https://github.com/mrhavens/Dedockify)** (написан на Python)
  ```sh
  sudo docker run -v /var/run/docker.sock:/var/run/docker.sock --rm mrhavens/dedockify <IMAGE_ID>
  ```