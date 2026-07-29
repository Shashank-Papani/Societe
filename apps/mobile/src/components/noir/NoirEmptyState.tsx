import { StyleSheet, Text, View } from "react-native";

import { NoirButton } from "@/components/noir/NoirButton";
import { colors, fontFamilies, spacing } from "@/theme";

type Props = {
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
  testID?: string;
};

export function NoirEmptyState({ title, body, actionLabel, onAction, testID }: Props) {
  return (
    <View style={styles.wrap} testID={testID}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.body}>{body}</Text>
      {actionLabel && onAction ? (
        <NoirButton label={actionLabel} onPress={onAction} variant="secondary" />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm, paddingVertical: spacing.lg },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
  },
  body: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    lineHeight: 20,
  },
});
