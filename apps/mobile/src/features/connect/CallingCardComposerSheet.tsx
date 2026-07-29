import { useState } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  CALLING_CARD_REASON_CODES,
  type CallingCardReasonCode,
  type DiscoverableUser,
} from "@/features/connect/api";
import { ProfileAvatar } from "@/features/connect/ProfileAvatar";
import { reasonCodeLabel } from "@/features/connect/queueHelpers";
import { colors, fontFamilies } from "@/theme";

export const CUSTOM_MESSAGE_MAX = 160;

type Props = {
  visible: boolean;
  person: DiscoverableUser | null;
  venueName: string | null;
  submitting?: boolean;
  submitError?: string | null;
  onClose: () => void;
  onSend: (input: {
    reasonCode: CallingCardReasonCode | null;
    customMessage: string | null;
  }) => void;
};

/**
 * Draft state lives in this component. Parent should remount via `key={userId}`
 * when opening for a new person so Cancel → re-open starts clean, while a
 * failed send (same key) preserves the entered message.
 */
export function CallingCardComposerSheet({
  visible,
  person,
  venueName,
  submitting,
  submitError,
  onClose,
  onSend,
}: Props) {
  const [reasonCode, setReasonCode] = useState<CallingCardReasonCode | null>(null);
  const [customMessage, setCustomMessage] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  if (!person) {
    return null;
  }

  const trimmed = customMessage.trim();
  const canSend = Boolean(reasonCode || trimmed) && !submitting;

  const handleSend = () => {
    if (!reasonCode && !trimmed) {
      setLocalError("Choose an opener or write a message.");
      return;
    }
    setLocalError(null);
    onSend({
      reasonCode,
      customMessage: trimmed ? trimmed.slice(0, CUSTOM_MESSAGE_MAX) : null,
    });
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
      testID="calling-card-composer"
    >
      <View style={styles.backdrop}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Dismiss composer"
          style={StyleSheet.absoluteFill}
          onPress={onClose}
          testID="calling-card-composer-dismiss"
        />
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.sheetWrap}
        >
          <SafeAreaView edges={["bottom"]} style={styles.sheet}>
            <View style={styles.dragHandle} />
            <View style={styles.header}>
              <ProfileAvatar
                displayName={person.display_name}
                handle={person.handle}
                size={48}
              />
              <View style={styles.headerCopy}>
                <Text style={styles.name} numberOfLines={1}>
                  {person.display_name}
                </Text>
                <Text style={styles.handleText} numberOfLines={1}>
                  @{person.handle}
                </Text>
                {venueName ? (
                  <Text style={styles.venue} numberOfLines={1}>
                    {venueName}
                  </Text>
                ) : null}
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Close"
                testID="calling-card-composer-close"
                onPress={onClose}
                hitSlop={10}
                style={styles.closeBtn}
              >
                <Text style={styles.closeText}>Close</Text>
              </Pressable>
            </View>

            <Text style={styles.title} accessibilityRole="header">
              Send a Calling Card
            </Text>
            <Text style={styles.support}>
              Choose an opener or write your own message.
            </Text>

            <ScrollView
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
              contentContainerStyle={styles.body}
            >
              <View style={styles.chips} testID="calling-card-composer-reasons">
                {CALLING_CARD_REASON_CODES.map((code) => {
                  const selected = reasonCode === code;
                  return (
                    <Pressable
                      key={code}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}
                      testID={`calling-card-reason-${code}`}
                      onPress={() =>
                        setReasonCode((current) => (current === code ? null : code))
                      }
                      style={[styles.chip, selected && styles.chipSelected]}
                    >
                      <Text
                        style={[styles.chipText, selected && styles.chipTextSelected]}
                      >
                        {reasonCodeLabel(code)}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>

              <Text style={styles.inputLabel} accessibilityRole="text">
                Message
              </Text>
              <TextInput
                accessibilityLabel="Add a message"
                testID="calling-card-custom-message"
                value={customMessage}
                onChangeText={(value) => {
                  setCustomMessage(value.slice(0, CUSTOM_MESSAGE_MAX));
                  setLocalError(null);
                }}
                placeholder="Add a message…"
                placeholderTextColor={colors.textSecondary}
                multiline
                maxLength={CUSTOM_MESSAGE_MAX}
                style={styles.input}
              />
              <Text
                style={styles.counter}
                testID="calling-card-message-count"
                accessibilityLiveRegion="polite"
              >
                {customMessage.length}/{CUSTOM_MESSAGE_MAX}
              </Text>

              {localError || submitError ? (
                <Text style={styles.error} testID="calling-card-composer-error">
                  {localError ?? submitError}
                </Text>
              ) : null}
            </ScrollView>

            <View style={styles.actions}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Cancel"
                testID="calling-card-composer-cancel"
                onPress={onClose}
                disabled={Boolean(submitting)}
                style={({ pressed }) => [
                  styles.cancelBtn,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.cancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Send Calling Card"
                accessibilityState={{ disabled: !canSend }}
                testID="calling-card-composer-send"
                disabled={!canSend}
                onPress={handleSend}
                style={({ pressed }) => [
                  styles.sendBtn,
                  !canSend && styles.disabled,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.sendText}>
                  {submitting ? "Sending…" : "Send Calling Card"}
                </Text>
              </Pressable>
            </View>
          </SafeAreaView>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(4, 9, 7, 0.72)",
  },
  sheetWrap: { maxHeight: "92%" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    paddingHorizontal: 20,
    paddingTop: 10,
    gap: 10,
  },
  dragHandle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: "rgba(255,255,255,0.16)",
    marginBottom: 4,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  headerCopy: { flex: 1, gap: 2 },
  name: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 24,
  },
  handleText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  venue: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 12,
  },
  closeBtn: {
    minHeight: 44,
    justifyContent: "center",
    paddingHorizontal: 4,
  },
  closeText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 28,
  },
  support: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
    marginBottom: 4,
  },
  body: { gap: 10, paddingBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    minHeight: 36,
    paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.background,
    alignItems: "center",
    justifyContent: "center",
  },
  chipSelected: {
    borderColor: "rgba(185, 249, 8, 0.5)",
    backgroundColor: "rgba(185, 249, 8, 0.12)",
  },
  chipText: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
  },
  chipTextSelected: { color: colors.lime },
  inputLabel: {
    color: colors.gold,
    fontFamily: fontFamilies.geistBold,
    fontSize: 12,
    letterSpacing: 1.1,
    marginTop: 4,
  },
  input: {
    minHeight: 96,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.background,
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 15,
    paddingHorizontal: 14,
    paddingVertical: 12,
    textAlignVertical: "top",
  },
  counter: {
    alignSelf: "flex-end",
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 12,
  },
  error: {
    color: colors.danger,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
  },
  actions: {
    flexDirection: "row",
    gap: 10,
    paddingBottom: 8,
    paddingTop: 4,
  },
  cancelBtn: {
    minHeight: 48,
    paddingHorizontal: 16,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  cancelText: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 13,
  },
  sendBtn: {
    flex: 1,
    minHeight: 48,
    borderRadius: 999,
    backgroundColor: colors.lime,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 14,
  },
  sendText: {
    color: colors.limeInk,
    fontFamily: fontFamilies.geistBold,
    fontSize: 13,
  },
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.9 },
});
