// CLI configuration. See https://remotion.dev/docs/config
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
// Optional: point at an installed Chrome Headless Shell when downloads are blocked,
// e.g. REMOTION_BROWSER=/path/to/headless_shell npm run render:sample
if (process.env.REMOTION_BROWSER) {
  Config.setBrowserExecutable(process.env.REMOTION_BROWSER);
}
