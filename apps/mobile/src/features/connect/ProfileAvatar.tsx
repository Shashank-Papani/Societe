import { Image } from "expo-image";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import {
  avatarAccent,
  avatarInitials,
} from "@/features/connect/connectPresentation";
import { colors, fontFamilies } from "@/theme";

type Props = {
  displayName: string;
  handle?: string | null;
  /** Approved signed profile URL only — never pending/rejected media. */
  photoUrl?: string | null;
  size?: number;
  testID?: string;
};

function isUsablePhotoUrl(url: string | null | undefined): url is string {
  if (!url) {
    return false;
  }
  const trimmed = url.trim();
  return trimmed.startsWith("https://") || trimmed.startsWith("http://");
}

export function ProfileAvatar({
  displayName,
  handle,
  photoUrl,
  size = 52,
  testID,
}: Props) {
  const [failed, setFailed] = useState(false);
  const seed = handle?.trim() || displayName;
  const initials = avatarInitials(displayName, handle);
  const showRemote = isUsablePhotoUrl(photoUrl) && !failed;

  return (
    <View
      testID={testID}
      style={[
        styles.wrap,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: avatarAccent(seed),
        },
      ]}
      accessibilityRole="image"
      accessibilityLabel={`${displayName} avatar`}
    >
      {showRemote ? (
        <Image
          source={{ uri: photoUrl }}
          style={{ width: size, height: size, borderRadius: size / 2 }}
          contentFit="cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <Text style={[styles.initials, { fontSize: Math.round(size * 0.34) }]}>
          {initials}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  initials: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
  },
});
