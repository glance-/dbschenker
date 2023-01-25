DbSchenker custom_component
=========================

This is a custom component for home-assistant to track dbschenker packages.

Its activated by adding the following to your configuration.yaml:
```yaml
sensor:
  - platform: dbschenker
```

After that you can start to track your packages by calling the service
`dbschenker.register`  with a argument looking like
`{"package_id": "UA123456789SE"}` to have home-assistant start tracking
that package.

And when you loose interest in that package, you just stop tracking it by
calling `dbschenker.unregister` with a corresponding argument.


To view all your packages in a nice fashion, I use the auto-entities[1]
card to view them all as a list in lovelace:
```yaml
      - card:
          type: entities
        filter:
          include:
            - domain: dbschenker
        type: 'custom:auto-entities'
```

This is reverse engineered code.

This component shares quite a bit of code and architecture
with my package tracker for Postnord[2], DHL[3] and bring[4].


1. https://github.com/thomasloven/lovelace-auto-entities
2. https://github.com/glance-/postnord
3. https://github.com/glance-/dhl
4. https://github.com/glance-/bring
