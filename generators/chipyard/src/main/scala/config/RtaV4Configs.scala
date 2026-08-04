package chipyard

import org.chipsalliance.cde.config.Config

/** One Rocket core with the frozen RTA V4 artifact at 0x1005_0000. */
class RtaV4RocketConfig extends Config(
  new chipyard.rta_v4.WithRtaV4() ++
  new freechips.rocketchip.rocket.WithNHugeCores(1) ++
  new chipyard.config.AbstractConfig)
