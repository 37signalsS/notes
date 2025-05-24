Нужно зарегистрироваться на сайте DockerHub и залить туда наш образ:

``` sh
docker login -u <dockerhub username> 
```

Прежде чем залить образ, повесим на него тег и укажем, что он будет находиться в репозитории с именем <dockerhub username>.

``` sh
docker tag my-caddy-image:0.0.1 <dockerhub username>/my-caddy-image:0.0.1
```

``` sh
docker push <dockerhub username>/my-caddy-image:0.0.1
```


