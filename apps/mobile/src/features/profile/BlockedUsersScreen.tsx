import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/auth/AuthProvider";
import {
  fetchBlockedUsers,
  unblockUser,
  type BlockedUser,
} from "@/features/connect/api";
import { ProfileAvatar } from "@/features/connect/ProfileAvatar";
import { colors, fontFamilies } from "@/theme";

export function BlockedUsersScreen() {
  const auth = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const listQuery = useQuery({
    queryKey: ["me", "blocked-users"],
    queryFn: fetchBlockedUsers,
    enabled: auth.status === "authenticated",
  });

  const unblockMutation = useMutation({
    mutationFn: (userId: string) => unblockUser(userId),
    onSuccess: async (_data, userId) => {
      setActionError(null);
      queryClient.setQueryData<BlockedUser[]>(["me", "blocked-users"], (current) =>
        (current ?? []).filter((item) => item.user_id !== userId),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["me", "blocked-users"] }),
        queryClient.invalidateQueries({ queryKey: ["connect"] }),
      ]);
    },
    onError: (error: Error) => {
      if (__DEV__) {
        console.warn("[blocked.unblock]", error);
      }
      setActionError("Couldn’t unblock. Try again.");
    },
  });

  const confirmUnblock = (user: BlockedUser) => {
    Alert.alert(
      `Unblock ${user.display_name}?`,
      "They may be able to find you and send new Calling Cards again, depending on both users’ privacy settings.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Unblock",
          style: "destructive",
          onPress: () => unblockMutation.mutate(user.user_id),
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]} testID="blocked-users-screen">
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          testID="blocked-users-back"
          onPress={() => router.back()}
          hitSlop={8}
          style={styles.backBtn}
        >
          <Text style={styles.backText}>Back</Text>
        </Pressable>
        <Text style={styles.title} accessibilityRole="header">
          Blocked Users
        </Text>
      </View>

      {listQuery.isLoading ? (
        <ActivityIndicator color={colors.lime} style={styles.loader} />
      ) : null}

      {listQuery.isError ? (
        <View style={styles.empty}>
          <Text style={styles.emptyTitle}>Couldn’t load blocked users</Text>
          <Pressable
            onPress={() => {
              void listQuery.refetch();
            }}
            style={styles.retry}
          >
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : null}

      {!listQuery.isLoading && !listQuery.isError && (listQuery.data ?? []).length === 0 ? (
        <View style={styles.empty} testID="blocked-users-empty">
          <Text style={styles.emptyTitle}>No blocked users</Text>
          <Text style={styles.emptyCopy}>People you block will appear here.</Text>
        </View>
      ) : null}

      <FlatList
        data={listQuery.data ?? []}
        keyExtractor={(item) => item.user_id}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => (
          <View style={styles.row} testID={`blocked-user-${item.user_id}`}>
            <ProfileAvatar
              displayName={item.display_name}
              handle={item.handle}
              photoUrl={item.profile_photo_url}
              size={48}
            />
            <View style={styles.copy}>
              <Text style={styles.name} numberOfLines={1}>
                {item.display_name}
              </Text>
              <Text style={styles.handle} numberOfLines={1}>
                @{item.handle}
              </Text>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Unblock ${item.display_name}`}
              testID={`blocked-user-unblock-${item.user_id}`}
              disabled={
                unblockMutation.isPending && unblockMutation.variables === item.user_id
              }
              onPress={() => confirmUnblock(item)}
              style={({ pressed }) => [styles.unblockBtn, pressed && styles.pressed]}
            >
              <Text style={styles.unblockText}>Unblock</Text>
            </Pressable>
          </View>
        )}
      />

      {actionError ? (
        <Text style={styles.error} accessibilityLiveRegion="polite" testID="blocked-users-error">
          {actionError}
        </Text>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 12,
    gap: 8,
  },
  backBtn: { minHeight: 44, justifyContent: "center", alignSelf: "flex-start" },
  backText: {
    color: colors.lime,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 14,
  },
  title: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 34,
  },
  loader: { marginTop: 24 },
  list: { paddingHorizontal: 20, paddingBottom: 40, gap: 12 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 14,
  },
  copy: { flex: 1, gap: 2 },
  name: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 22,
  },
  handle: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistMedium,
    fontSize: 13,
  },
  unblockBtn: {
    minHeight: 44,
    paddingHorizontal: 12,
    justifyContent: "center",
  },
  unblockText: {
    color: colors.danger,
    fontFamily: fontFamilies.geistSemiBold,
    fontSize: 13,
  },
  empty: { paddingHorizontal: 20, paddingTop: 32, gap: 8 },
  emptyTitle: {
    color: colors.textPrimary,
    fontFamily: fontFamilies.instrumentSerif,
    fontSize: 26,
  },
  emptyCopy: {
    color: colors.textSecondary,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 14,
  },
  retry: {
    alignSelf: "flex-start",
    marginTop: 8,
    minHeight: 44,
    justifyContent: "center",
  },
  retryText: {
    color: colors.lime,
    fontFamily: fontFamilies.geistBold,
    fontSize: 13,
  },
  error: {
    color: colors.danger,
    fontFamily: fontFamilies.geistRegular,
    fontSize: 13,
    paddingHorizontal: 20,
    paddingBottom: 16,
  },
  pressed: { opacity: 0.88 },
});
