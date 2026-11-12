from homey_esphomedriver import EspHomeDevice


class __DEVICE_CLASS_NAME__(EspHomeDevice):
    async def on_esphome_init(self, client):
        # Bind each capability in driver.compose.json to an ESPHome entity,
        # named by its domain and its name as written in the firmware YAML.
        self.register_capability("measure_temperature", "sensor", "Temperature")


homey_export = __DEVICE_CLASS_NAME__
