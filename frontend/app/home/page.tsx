import { Meteors } from "@/components/ui/meteors";

export default function HomePage() {
  return (
    <div>
        <Meteors color="#88c0d0" tailColor="rgba(136, 192, 208, 0.5)">
          <div className="flex h-screen w-screen items-center justify-center">
            <h1 className="text-4xl font-bold text-white">Welcome to the Meteor Shower</h1>
          </div>
        </Meteors>
    </div>
  );
}