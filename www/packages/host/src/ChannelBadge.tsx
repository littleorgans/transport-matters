import { useMeta } from "@tm/core";
import "./channel-badge.css";

export function ChannelBadge() {
  const { meta } = useMeta();

  if (
    meta === undefined ||
    meta.channelBadge === undefined ||
    meta.channelBadge === null ||
    meta.channel === "stable"
  ) {
    return null;
  }

  const badge = meta.channelBadge;
  return (
    <div
      aria-label={`${meta.channelLabel} channel`}
      className="channel-badge"
      role="status"
      style={{ backgroundColor: badge.hex }}
    >
      {badge.text}
    </div>
  );
}
